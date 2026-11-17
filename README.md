# social2md

**一条链接进去，一份完整文档出来。**

A share link in, a complete structured document out — for Chinese social media.

小红书、抖音、快手的分享链接，直接变成带**视频全文、图文文字、关键细节**的结构化 Markdown + HTML。不是只给你标题和简介。

- **抖音**：扫码登录一次，让浏览器自己签名、CDP 截获数据。不逆向 `a_bogus`，不用手配 cookie。
- **图文笔记**：Apple Vision OCR，图片里写的字也提取出来。
- **一个 Skill 通吃**：Claude Code / Codex / WorkBuddy / Pi / Hermes / OpenClaw 都能自动发现。
- **全部本地**：faster-whisper 转录 + Apple Vision OCR + Markdown 转 HTML，内容不上传第三方。

---

## 为什么做这个

刷到一条有用的视频或图文，想留下来仔细看，通常只有三条路：

1. 下载视频——存了一堆 mp4，从来没再看。
2. 复制标题和简介——真正的干货在视频里和图片里，全丢了。
3. 找在线解析服务——上传内容到别人的服务器，接口随时失效。

现有的开源工具要么只覆盖 YouTube / TikTok，要么只做下载不做内容，要么要求你自己逆向签名、维护 cookie。`social2md` 想做的是**第四种**：给一条链接，拿回一份真正能读、能搜、能交给 Agent 的完整文档。

## 和同类项目的区别

截至 2026-11 的公开信息，尽量客观对比：

| 项目 | Stars | 覆盖 | 视频转文字 | 图文 OCR | 登录方式 |
|---|---:|---|---|---|---|
| **social2md** | — | 小红书 + 抖音 + 快手 | 本地 faster-whisper | **Apple Vision** | 抖音扫码一次，其余免登录 |
| `chubbyguan/chubbyskills` | ~1300 | 10+ 中文平台 + 知识库 | 字幕优先 + 转录 | 不做 OCR | 小红书需自配 cookie |
| `JimmySadek/video-fetcher-to-markdown` | ~530 | YouTube / IG / TikTok / X | 本地 Whisper | 短视频抽帧 | 视平台而定 |
| `chenxiachan/xhs-claude-skills` | ~430 | 仅小红书 | 部分支持 | 不突出 | 依赖 Claude Code |
| `putyy/res-downloader`、`JoeanAmier/XHS-Downloader` | 1.3w–2.1w | 多平台 | 不做 | 不做 | 多为下载器 |

一句话：**下载器不产内容，英文工具不覆盖中文平台，中文知识库工具不做 OCR 且要你伺候 cookie。** 我们补的是中间那块。

## 支持平台

| 平台 | 链接形态 | 登录 | 输出 |
|---|---|---|---|
| 小红书 | `xhslink.cn`、`xiaohongshu.com` | 不需要 | 视频转录 / 图文 OCR / 结构化文档 |
| 抖音 | `v.douyin.com`、`douyin.com`、15–19 位 aweme_id | **一次性扫码** | 视频转录 / 结构化文档 |
| 快手 | `v.kuaishou.com`、`kuaishou.com` | 不需要 | 视频转录 / 结构化文档 |

> 小红书部分旧笔记缺少 `xsec_token` 会解析失败，换新分享链接即可。平台接口会变，失败时重跑解析步骤拿新的签名 URL。

---

## 快速开始

### 1. 安装

```bash
git clone https://github.com/EvansShuyw/social2md.git
cd social2md
python3 -m pip install faster-whisper av
```

第一次转录会从 `hf-mirror` 下载约 1.6 GB 模型。国内网络建议先设：

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

让 Agent 框架发现这个 Skill —— 跑一键脚本，它会软链到全部 8 个框架路径（幂等，可重复运行）：

```bash
chmod +x install.sh && ./install.sh
```

或者手动软链到你在用的框架：

```bash
ln -s "$(pwd)" ~/.claude/skills/social2md           # Claude Code
ln -s "$(pwd)" ~/.codex/skills/social2md            # Codex
ln -s "$(pwd)" ~/.workbuddy/skills/social2md        # WorkBuddy
ln -s "$(pwd)" ~/.hermes/skills/social2md           # Hermes
```

`/Users/...` 之类绝对路径不需要，clone 到哪都能用。

> 仓库根目录就是 Skill 目录，`SKILL.md` 的 `name` 已是 `social2md`。

### 2. 抖音一次性登录（只做一次）

```bash
node scripts/douyin/login.mjs --timeout 600
```

会弹出浏览器显示二维码，用抖音 App 扫码。二维码约 2–3 分钟过期，脚本会自动刷新。登录态保存在 `~/.workbuddy/douyin-profile`（可用 `DOUYIN_PROFILE` 改路径）。

> 窗口可能被其他应用挡住。脚本会尝试激活浏览器；也可以自己切过去看。

### 3. 跑一条链接

```bash
# 小红书：先拿元数据
python3 scripts/xhs/fetch_xhs.py "<小红书链接>" --out note.json

# 抖音：短链 -> aweme_id -> CDP 截获
node scripts/douyin/resolve_link.mjs "<抖音分享链接>"
node scripts/douyin/cdp_extract.mjs "<aweme_id 或链接>" --out meta.json

# 快手：从分享页直接解析
node scripts/kuaishou/resolve_kuaishou.mjs "<快手分享链接>" --out meta.json
```

拿到签名播放地址后，下载、转录、渲染：

```bash
python3 scripts/core/download_video.py "<SIGNED_URL>" --out media.mp4
python3 scripts/core/transcribe.py media.mp4 --out-prefix transcript
python3 scripts/core/md_to_html.py digest.md --out digest.html \
    --title "标题" --subtitle "作者 · 来源" --theme blue
```

图文笔记走另一条分支：

```bash
python3 scripts/xhs/download_images.py note.json --out-dir images
python3 scripts/xhs/ocr_images.py images/manifest.json --out ocr.txt
```

然后把 OCR 文本和元数据整理成结构化 Markdown 即可。

**实际使用时不必手写这些命令**——把链接丢给任意装了这个 Skill 的 Agent，它会按域名自动路由、选平台参考文档、跑完整流程并产出文档。上面的命令是给想手动调用或二次开发的人看的。

---

## 你会得到什么

- `digest.md` —— 结构化中文文档：核心结论、分主题内容、带时间戳的关键段落、术语与数据、存疑处标注。
- `digest.html` —— 带样式的阅读版，蓝/橙/绿三色主题。
- `transcript.txt` / `transcript.srt` —— 带时间戳的逐字稿和字幕。
- `ocr.txt` —— 图文笔记的图片文字（macOS）。

主旨和标题不等于内容：文档里会明确标出"标题党"和实际内容不一致的地方，不编造、不脑补。财经类内容里的数字会提示与实时行情核对。

---

## 它是怎么工作的

```
分享链接
  → 平台适配器（小红书 / 抖音 / 快手）
      → 元数据 + 签名媒体地址
  → 共享 core：断点续传下载（自动推断 UA + Referer）
  → 本地转录 faster-whisper / 本地 Apple Vision OCR
  → 结构化 Markdown → 带样式 HTML
```

几个关键设计：

- **单一真相源**：下载、转录、HTML 渲染都在 `scripts/core/`，修一处三平台受益；平台差异只在适配层。
- **不逆向签名**：抖音让已登录的浏览器自己发请求，通过 CDP 在 `loadingFinished` 后取响应体，绕开 `a_bogus`、`msToken`、`ArgusSecurity`。
- **静默失败防护**：抖音登录过期时接口会返回"看起来正常"的旧数据。`cdp_extract.mjs` 输出 `VERDICT=OK/EMPTY/BAD_STATUS/NO_PLAY_URL/STALE`，只有 `OK` 才能继续。
- **CDN 坑位**：抖音签名播放链接不带浏览器 UA + Referer 会返回 355 字节的 403 页面，core 脚本已默认处理。

各平台的完整坑位记录在 `references/`，按需加载，不占日常上下文。

## Agent 框架支持

Skill 遵循开放的 Agent Skills 规范（`SKILL.md` + YAML frontmatter + `references/` + `scripts/`），已验证或被官方支持软链的框架：

| 框架 | 目录 |
|---|---|
| WorkBuddy | `~/.workbuddy/skills/` |
| Claude Code | `~/.claude/skills/` |
| Codex | `~/.agents/skills/`、`~/.codex/skills/` |
| Pi | `~/.agents/skills/`、`~/.pi/agent/skills/` |
| DeepSeek Harness | `~/.agents/skills/`、`~/.dsh/skills/` |
| OpenClaw | `~/.openclaw/workspace/skills/` |
| Hermes | `~/.hermes/skills/` |

`~/.agents/skills/` 是 Codex / Pi / DeepSeek Harness 的共同扫描根，链一次三家通吃。

## 依赖

| 用途 | 依赖 |
|---|---|
| 本地转录 | Python 3.10+、`faster-whisper`、`av`；首次下载 ~1.6 GB 模型 |
| 图文 OCR | macOS + Xcode command-line tools（`swiftc`）；非 macOS 可用 Agent 自身的视觉能力读图 |
| 抖音 / 快手 | Node.js 22+、Chrome/Chromium、Playwright |
| 下载 | `curl`（脚本内置纯 Python Range 兜底） |

浏览器路径默认自动发现，也可显式指定：

```bash
export DOUYIN_CHROME=/path/to/Chromium
```

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 抖音解析出旧数据 / 空内容 | 登录态过期或触发风控，看 `VERDICT` | 重跑 `login.mjs` 扫码 |
| 下载下来只有 355 字节 | 403 HTML 被当成视频 | 用 core 脚本，别用裸 `curl` |
| 小红书解析失败 | 链接缺 `xsec_token` | 换 App 内重新分享的链接 |
| 快手拿不到标题 | 分享页结构变化 | 脚本会从 DOM 兜底提取，失败时更新适配层 |
| 转录报 `metadata_errors` | PyAV 19+ 与 faster-whisper 不兼容 | core 脚本已内置补丁 |
| `SingletonLock` 错误 | 同一 profile 开了两个浏览器 | 关掉另一个，清理锁文件 |
| 二维码看不到 | 窗口被遮挡 | 切到浏览器窗口，脚本每 ~100 秒刷新二维码 |

## 隐私与安全

- 转录、OCR、HTML 渲染全部本地完成，音视频和图片不上传第三方。
- 抖音登录态只存在本机 profile 目录；不要提交或分享该目录。
- 复制仓库后请检查没有带入 `*.env`、cookie、token、个人 open_id。
- 平台链接和接口属于各平台所有，本项目与这些平台无关联、未获背书。请遵守当地法律与平台条款，仅用于合法的个人或研究用途。

## 项目结构

```
social2md/
├── SKILL.md                    Agent 入口：路由规则 + 通用流程
├── references/
│   ├── xhs.md                  小红书坑位与字段结构
│   ├── douyin.md               抖音风控、CDP 时序、登录与判据
│   └── kuaishou.md             快手分享页解析兜底
├── scripts/
│   ├── core/                   下载 / 转录 / HTML（共享，平台无关）
│   │   ├── download_video.py
│   │   ├── transcribe.py
│   │   └── md_to_html.py
│   ├── xhs/                    fetch_xhs.py · download_images.py · ocr_images.py · ocr_vision.swift
│   ├── douyin/                 resolve_link.mjs · login.mjs · cdp_extract.mjs · dy_common.mjs
│   └── kuaishou/               resolve_kuaishou.mjs
├── install.sh                  一键软链到所有 Agent 框架
├── LICENSE
└── .gitignore
```

## 路线图

- [ ] 字幕优先路径（有官方字幕时跳过 Whisper，进一步提速）
- [ ] 更多平台：B站 / 公众号 / 微博
- [ ] 输出结构化字段（YAML frontmatter），便于 Obsidian / Dataview 检索
- [ ] 更细的财经数字校验与术语词典
- [ ] 一键 `npx skills add` 安装

## 贡献

欢迎提 Issue 和 PR。新增平台请以「薄适配层 + 复用 core」为原则；踩过的坑请写进 `references/<platform>.md`，让下一个人不用再踩。提交前确认：命令实测通过、示例里没有个人路径或凭据、没有把 cookie / token / 采集原文提交进仓库。

## License

MIT — 见 [LICENSE](LICENSE)。

---

> 如果这个项目帮你省了时间，点个 star 让更多人看到。它解决的问题很具体：把中文社媒里那些"刷过就忘"的内容，真正留下来。
