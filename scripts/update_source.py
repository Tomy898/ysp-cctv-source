#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""央视频专属接口源 · 每日刷新脚本

由 .github/workflows/update-source.yml 每天 06:00（北京时间）调用，做两件事：

1. 静态体检 ysp-fongmi.py（不联网、不启动本地 HLS 代理）：
   - 语法可解析；
   - 定义了 class Spider，且宿主约定的 7 个方法一个不少；
   - 频道表结构合法（字段数、slug 唯一、清晰度取值、分组可归属）。
   任何一项不通过就以退出码 2 结束 —— 让 GitHub Actions 变红报警，而不是
   把一个坏掉的接口源悄悄发布出去。

2. 从脚本本身读出频道表 / 分组 / 请求 UA，重新生成可订阅的源索引 ysp.json：
   版本号、更新时间、频道总数、分组统计、脚本指纹（sha256）以及订阅用的 raw 地址。
   仓库地址优先取 --repo，其次 GITHUB_REPOSITORY，再次 git remote origin，
   都没有时沿用已有 ysp.json 里的地址，最后才落到占位符。

只依赖 Python 标准库，不需要第三方包。

用法:
    python scripts/update_source.py
    python scripts/update_source.py --repo owner/name --ref main --port 8899
"""

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "ysp-fongmi.py"
DEFAULT_OUT = ROOT / "ysp.json"
DEFAULT_REF = "main"
DEFAULT_PORT = 8899

# 宿主按固定协议调用的方法，少一个宿主页面上就会出现异常。
REQUIRED_METHODS = [
    "getName",
    "init",
    "homeContent",
    "categoryContent",
    "detailContent",
    "searchContent",
    "playerContent",
]

PLACEHOLDER_REPO = "YOUR_GITHUB_NAME/ysp-cctv-source"

def _tz():
    """北京时间：优先用系统时区库，取不到就退回固定 UTC+8。"""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Asia/Shanghai")
    except Exception:
        return timezone(timedelta(hours=8))


def _fail(msg):
    print("::error::%s" % msg, file=sys.stderr)
    return 2


def audit_source(text):
    """体检脚本结构。返回 (tree, 错误消息列表)。"""
    errors = []
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return None, ["ysp-fongmi.py 语法错误: 第 %s 行 %s" % (e.lineno, e.msg)]

    cls = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Spider":
            cls = node
            break
    if cls is None:
        errors.append("找不到 class Spider，宿主无法加载该插件")
        return tree, errors

    defined = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    missing = [m for m in REQUIRED_METHODS if m not in defined]
    if missing:
        errors.append("Spider 缺少宿主约定方法: %s" % ", ".join(missing))

    return tree, errors


def load_plugin(path):
    """以普通 Python 模块方式载入插件，读出频道表等常量。

    插件顶部对 base.spider 的导入是 try/except 包裹的，脱离宿主也能导入；
    导入过程只执行常量与类定义，不会联网、不会起本地服务。
    """
    spec = importlib.util.spec_from_file_location("ysp_fongmi", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_channels(mod):
    """频道表体检。返回 (频道行列表, 分组统计, 警告列表, 错误列表)。"""
    warns, errors = [], []
    channels = list(getattr(mod, "CHANNELS", []) or [])
    group_defs = list(getattr(mod, "GROUP_DEFS", []) or [])
    if not channels:
        errors.append("CHANNELS 为空，接口源没有任何频道")
    if not group_defs:
        errors.append("GROUP_DEFS 为空，无法生成分类")

    slugs, seen = [], set()
    for row in channels:
        if len(row) != 5:
            errors.append("频道行字段数不是 5: %r" % (row,))
            continue
        slug, name, sid, pid, defn = row
        for label, value in (("slug", slug), ("名称", name), ("sid", sid), ("pid", pid), ("清晰度", defn)):
            if not str(value or "").strip():
                errors.append("频道 %s 的 %s 为空" % (slug, label))
        if slug in seen:
            errors.append("频道 slug 重复: %s" % slug)
        seen.add(slug)
        slugs.append(slug)

    slugs = [s for s in slugs if isinstance(s, str)]
    known = {g[0] for g in group_defs}
    groups = []
    unknown = []
    for gid, gname in group_defs:
        members = [s for s in slugs if mod._group_of(s) == gid]
        groups.append({"type_id": gid, "type_name": gname, "count": len(members)})
    for s in slugs:
        if mod._group_of(s) not in known:
            unknown.append(s)
    if unknown:
        errors.append("以下频道没有归属分组: %s" % ", ".join(sorted(unknown)))

    total = sum(g["count"] for g in groups)
    if total != len(slugs):
        errors.append("分组统计合计 %d 与频道数 %d 不一致（可能 _group_of 逻辑有问题）" % (total, len(slugs)))

    logos = getattr(mod, "LOGO_REMOTE", {}) or {}
    local_logos = getattr(mod, "LOGO_LOCAL", {}) or {}
    bare = [s for s in slugs if s not in logos and s not in local_logos]
    if bare:
        warns.append("以下频道没有配台标: %s" % ", ".join(bare))

    return channels, groups, warns, errors


def resolve_repo(explicit, existing, root=ROOT):
    """确定 owner/repo。顺序：参数 > GITHUB_REPOSITORY > git remote > 已有配置。"""
    if explicit and "/" in explicit:
        return explicit.strip()
    env = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in env:
        return env.strip()
    try:
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(root), capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            m = re.search(r"github\.com[:/]+([^/]+)/([^/\s]+?)(?:\.git)?$", out.stdout.strip())
            if m:
                return "%s/%s" % (m.group(1), m.group(2))
    except Exception:
        pass
    if existing and "/" in existing:
        return existing.strip()
    return ""


def repo_from_existing_json(path):
    """从已有 ysp.json 的订阅地址里反推 owner/repo。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        api = ((data.get("sites") or [{}])[0].get("api") or "")
        m = re.search(r"raw\.githubusercontent\.com/([^/]+)/([^/]+)/", api)
        if m:
            return "%s/%s" % (m.group(1), m.group(2))
    except Exception:
        pass
    return ""


def build_payload(mod, groups, repo, ref, port):
    """组装可订阅的源索引。sites / lives 字段沿用脚本自带用法，不做格式改造。"""
    tz = _tz()
    now = datetime.now(tz)
    raw_base = "https://raw.githubusercontent.com/%s/%s" % (repo, ref)
    raw_py = "%s/ysp-fongmi.py" % raw_base
    ua = getattr(mod, "UA", "") or ""

    payload = {
        "name": "央视频专属接口源",
        "version": now.strftime("%Y.%m.%d"),
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S%z"),
        "generator": "scripts/update_source.py",
        "channel_count": len(mod.CHANNELS),
        "groups": groups,
        "sites": [
            {
                "key": "ysp",
                "name": "央视频",
                "type": 3,
                "api": raw_py,
                "searchable": 1,
                "quickSearch": 1,
                "ext": {"port": port},
            }
        ],
        "lives": [
            {
                "name": "央视频直播",
                "api": raw_py,
                "url": "ysp://all",
                "ua": ua,
            }
        ],
    }
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description="刷新央视频专属接口源（ysp.json）")
    ap.add_argument("--source", default=str(DEFAULT_SOURCE), help="插件脚本路径")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出源索引路径")
    ap.add_argument("--repo", default="", help="owner/repo，缺省自动推断")
    ap.add_argument("--ref", default=os.environ.get("GITHUB_REF_NAME", DEFAULT_REF), help="分支名")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="插件内嵌本地代理端口")
    args = ap.parse_args(argv)

    src = Path(args.source)
    if not src.is_file():
        return _fail("找不到插件脚本: %s" % src)
    text = src.read_text(encoding="utf-8")
    digest = hashlib.sha256(src.read_bytes()).hexdigest()

    _, errors = audit_source(text)
    if errors:
        for e in errors:
            _fail(e)
        return 2

    try:
        mod = load_plugin(src)
    except Exception as e:
        return _fail("插件无法载入（脱离了 base.spider 也应能导入）: %s: %s" % (type(e).__name__, e))

    channels, groups, warns, errors2 = check_channels(mod)
    for w in warns:
        print("::warning::%s" % w)
    if errors2:
        for e in errors2:
            _fail(e)
        return 2

    existing = repo_from_existing_json(args.out)
    repo = resolve_repo(args.repo, existing)
    if not repo:
        print("::warning::没能确定 owner/repo，订阅地址先写成占位符；"
              "推到 GitHub 后由 Actions 自动改写，或本地加 --repo owner/name 再跑一次")
        repo = PLACEHOLDER_REPO

    payload = build_payload(mod, groups, repo, args.ref, args.port)
    payload["source"] = {
        "file": "ysp-fongmi.py",
        "sha256": digest,
        "channel_count": len(channels),
        "raw": payload["sites"][0]["api"],
    }
    # source 放到 groups 之后更顺手，重建一次键顺序
    ordered = {}
    for key in ("name", "version", "updated_at", "generator", "channel_count", "groups", "source",
                "sites", "lives"):
        ordered[key] = payload[key]
    text_out = json.dumps(ordered, ensure_ascii=False, indent=2) + "\n"

    out = Path(args.out)
    old = out.read_text(encoding="utf-8") if out.is_file() else ""
    changed = old.strip() != text_out.strip()
    if changed:
        out.write_text(text_out, encoding="utf-8", newline="\n")

    print("接口源 %s: %s" % (out.name, "已更新" if changed else "无变化"))
    print("  订阅地址: %s" % payload["sites"][0]["api"])
    print("  频道数  : %d（%s）" % (len(channels),
                                    " / ".join("%s %d" % (g["type_name"], g["count"]) for g in groups)))
    print("  更新时间: %s" % ordered["updated_at"])
    print("  脚本指纹: %s" % digest[:16])
    return 0


if __name__ == "__main__":
    sys.exit(main())