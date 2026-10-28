# 央视频专属接口源（ysp-cctv-source）

把央视频（CCTV / 卫视 / CGTN 等 63 路）直播，做成**你自己的专属接口源**：
一个 FongMi（影视TV）Python 插件 + 一份可订阅的源索引，托管在 GitHub 上，
由 GitHub Actions **每天早上 06:00（北京时间）自动刷新**。

推上去之后，你在播放器里填一个固定的 raw 链接，就能长期订阅；
源内容每天自动更新，你不用管。

---

## 目录结构

```
ysp-cctv-source/
├─ ysp-fongmi.py                     # 插件本体（改造完成，可直接被 FongMi 加载）
├─ ysp.json                          # 可订阅的源索引（由脚本生成，每天自动重写）
├─ ysp-cctv.m3u                      # 「央视频」直连清单（18 路央视，由脚本生成）
├─ scripts/
│  └─ update_source.py               # 每日刷新脚本：体检插件 + 重写源索引与直连清单
├─ .github/workflows/
│  └─ update-source.yml              # GitHub Actions：每天 06:00 自动刷新并提交
├─ .gitignore
└─ README.md
```

- 插件**只依赖 Python 标准库**，不需要 pip 安装任何包。
- 刷新脚本同样只用标准库。
- 插件本身**每天不改**（保持稳定，避免无意义提交）；每天变的只有 `ysp.json`
  （`ysp-cctv.m3u` 内容固定，不会天天产生提交）。

---

## 5 分钟上手

### 1) 推到 GitHub

新建一个仓库（建议命名 `ysp-cctv-source`），把本目录里的全部文件推上去：

```bash
git init
git add .
git commit -m "init: 央视频专属接口源"
git branch -M main
git remote add origin https://github.com/<你的用户名>/ysp-cctv-source.git
git push -u origin main
```

### 2) 打开 Actions 的写权限

仓库 → **Settings → Actions → General → Workflow permissions**，
选 **Read and write permissions**，保存。
（否则定时任务跑完没法把刷新后的 `ysp.json` 提交回仓库。）

### 3) 手点一次 Run workflow（关键一步）

仓库 → **Actions → 每日刷新央视频接口源 → Run workflow**。

这一次会读取**你的仓库地址**，把 `ysp.json` 里的订阅地址从占位符
`YOUR_GITHUB_NAME/ysp-cctv-source` 改写成真实地址，并自动提交。

### 4) 拿到并填订阅链接

刷新成功后，你的订阅地址是：

```
https://raw.githubusercontent.com/<你的用户名>/ysp-cctv-source/main/ysp.json
```

在播放器（FongMi / 影视TV）里按下面两种方式填：

**A. 直播（推荐，最像看电视）**
把 `ysp.json` 当作订阅源导入，或按文件里的 `lives` 段手动填：

```json
{
  "name": "央视频直播",
  "api": "https://raw.githubusercontent.com/<你的用户名>/ysp-cctv-source/main/ysp-fongmi.py",
  "url": "ysp://all",
  "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}
```

> 另外 `lives` 里还有一条名称为 **「央视频」** 的源，指向同仓库的 `ysp-cctv.m3u`（18 路央视直连地址）。
> 整份导入 `ysp.json` 时会一并带进去；也可单独添加，见下文「新增的『央视频』直连源」。

**B. 点播站点（分类 / 搜索 / 播放）**
对应 `ysp.json` 里的 `sites` 段：

```json
{
  "key": "ysp", "name": "央视频", "type": 3,
  "api": "https://raw.githubusercontent.com/<你的用户名>/ysp-cctv-source/main/ysp-fongmi.py",
  "searchable": 1, "quickSearch": 1, "ext": {"port": 8899}
}
```

> `ysp.json` 里的 `ua`、`api` 都是刷新脚本自动写好的，直接抄即可。

---

## 新增的「央视频」直连源

源索引的 `lives` 里除原有的「央视频直播」（插件源）外，多了一条名称为 **「央视频」** 的源，
它指向同仓库的 `ysp-cctv.m3u`，里面是 18 路央视的直连地址（CCTV1~CCTV17 与 CCTV5+）：

```
http://dl.qsaiv.cn:122/ysp.php?id=cctv1   # CCTV1
http://dl.qsaiv.cn:122/ysp.php?id=cctv2   # CCTV2
...
```

- 这条源与插件源**互不影响**，原来指向 `ysp-fongmi.py` 的条目保持原样。
- 切换清晰度、分类、搜索这些还是走插件源；这条只提供一条"打开就能播"的直连通道。
- `dl.qsaiv.cn:122` 是第三方跳转服务（不是央视官方接口），每次请求现场生成一个带时移
  窗口的 m3u8，链接本身有寿命；长期可用性取决于该服务，哪天停用这条源就会失效。
- 清单文件由 `scripts/update_source.py` 生成，频道表不变时内容不变，不会产生多余提交。

## 每天 06:00 自动更新是怎么实现的

`.github/workflows/update-source.yml`：

- 触发：`schedule: cron: '0 22 * * *'` + 手动 `workflow_dispatch`
  - GitHub Actions 的 cron 走 **UTC**；北京时间 06:00 = UTC 前一天 22:00，所以是 `0 22 * * *`。
- 步骤：拉仓库 → 装 Python 3.12 → 跑 `python scripts/update_source.py` → **只有内容有变化才提交**。
- 权限：`permissions: contents: write`（配合第 2 步的 Read and write 才能 push）。

刷新脚本每天做两件事：

1. **体检插件**（不联网、不启动本地代理）：语法可解析、`class Spider` 存在、宿主约定的 7 个方法齐全、
   频道表字段数正确、slug 唯一、分组能归属。任何一项不过关就以**退出码 2 + `::error::` 失败**，
   让 Actions 变红报警 —— 宁可变红，也不把一个坏掉的源悄悄发布出去。
2. **重写 `ysp.json`**：版本号、更新时间（北京时间）、频道总数、分组统计、脚本 sha256 指纹、
   以及订阅用的 raw 地址。仓库地址自动识别（`GITHUB_REPOSITORY` → `git remote origin` → 已有 `ysp.json`）。

### 手动刷新（可选的本地做法）

```bash
# 自动推断仓库地址（本地若不是 git 仓库会退回占位符）
python scripts/update_source.py

# 明确指定仓库与分支
python scripts/update_source.py --repo <你的用户名>/ysp-cctv-source --ref main --port 8899
```

---

## 什么时候用到这些参数

- `--source`　插件脚本路径，默认 `ysp-fongmi.py`
- `--out`　　输出源索引路径，默认 `ysp.json`
- `--repo`　　`owner/repo`，缺省自动推断
- `--ref`　　分支名，默认 `main`（CI 里自动取当前分支）
- `--port`　插件内嵌本地代理端口，默认 `8899`，与插件 `ext.port` 保持一致

---

## 已知限制（重要，先看再问）

1. **播放地址都是 `127.0.0.1`，必须在 App 内运行。**
   插件在 App 里起一个本地 HLS 代理（默认 `127.0.0.1:8899`）：央视给的是**时移 m3u8**，
   有寿命、分片地址会过期，播放器自己不会续窗口，所以由插件每 10 秒刷新清单、
   只保留贴近直播沿的 15 个分片。因此**没法在服务器上生成"别的设备点开就能播"的固定直播链接** ——
   视频分片本身由播放器直连央视 CDN，本地服务只发清单、不转发流量。
   换句话说：订阅链接是给**装了 FongMi 的 App**用的，不是给普通浏览器直接播的。
2. **定时可能延迟。** GitHub Actions 的 schedule 在高峰期会排队，实际执行时间可能比 06:00 晚上几分钟到几十分钟，
   属正常现象。
3. **4K / 高码率频道一律走 1080p。** 原版里的 4K Rust 后端在 Android 上跑不起来，已移除。
4. **台标**：63 路全部带台标。央视/卫视走公开台标库（四镜像轮试），库里没有的 5 路是内嵌自绘、不联网，
   取到的图本地缓存，第二次起直接读缓存。可用 `ext.logo` 切换 `local` / `remote` / `off`。
5. **网络环境**：插件访问央视 CDN 需要所处网络可达；跨网/海外环境不一定能稳定拉流。

---

## 常见问题

**Q：Actions 报错、`ysp.json` 提交失败（403 之类）？**
A：忘记开 Workflow permissions = Read and write。见上面第 2 步。

**Q：`ysp.json` 里订阅地址还是 `YOUR_GITHUB_NAME`？**
A：还没手点过 Run workflow。见上面第 3 步；或本地带 `--repo` 跑一次刷新脚本再提交。

**Q：想换端口？**
A：改 `ysp.json` 里 `sites[0].ext.port` 与工作流/刷新脚本的 `--port`，保持一致即可（插件默认 8899）。

---

## 校验

插件契约校验由 `okyspider-plugin` 的 `check_plugin.py` 完成（纯静态，不联网）：

```bash
python check_plugin.py ysp-fongmi.py
# 期望: 8 pass / 1 warn / 0 fail
```

其中唯一一条 WARN 是「`detailContent()` 里没看到 `#` 分隔符」——
本插件单频道直播就是**单集**，多集地址才需要 `#` 连接，这里**不适用**，属确认保留。

> 说明：脚本改造依据的是宿主的接口契约与静态校验，**实际拉流与播放未在本环境联网实测**，
> 首次使用请在 App 内确认可播。