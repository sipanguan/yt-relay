# yt-relay：借 GitHub Actions 让 Agent "看" YouTube 视频

## 为什么需要它

本机（阿里 DSW 容器）对 YouTube 是**双重封锁**，实测证据：

| 检测项 | 结果 |
|---|---|
| `www.youtube.com` DNS 解析 | `2001::1` ← **投毒**（假地址） |
| `redirector.googlevideo.com` DNS | `2a03:2880:...:face:b00c:...` ← Facebook 的 IPv6 前缀，明显伪造 |
| 用真实 IP 直连（`--resolve`） | `000` ← **IP 段也被阻断** |
| `1.1.1.1` / `8.8.8.8` / `dns.google` | 全 `000` |
| `chromewebstore.google.com` | `000` ← 所以浏览器翻墙插件**装不上** |
| `cloudfront.net`（FanVPN 备用源） | `000` ← 装了也连不上节点 |

**结论：任何浏览器 VPN 插件（FanVPN 等）在这台机器上都是死路**——它们治的是"浏览器应用层代理"，
治不了"这台机器出不去"。

### 但封锁是**域名级黑名单**，不是全封

实测**通**：`api.github.com` / `github.com` / `codeload.github.com` / `objects.githubusercontent.com` /
`exa.ai` / `www.bing.com` / `deno.com` / `vercel.com` / `netlify.com` / `render.com` / `fly.io` / `replit.com`

而 **GitHub Actions 的 runner 有完整外网**。于是：

```
本机 --(api.github.com 触发)--> GitHub Actions runner --(完整外网)--> YouTube
本机 <--(codeload.github.com 拉 tar)-- runner commit 结果回仓库
```

全程**不需要代理、不需要翻墙插件、不花钱**（公开仓库 Actions 免费；私有仓库每月 2000 分钟免费额度）。

## 目录

```
yt-relay/
├── .github/workflows/yt-watch.yml   # Actions 工作流（下载 + 抽帧 + 可选转写 + 提交回仓库）
├── yt_relay.py                      # 本机端：触发 / 等待 / 回取
└── README.md
```

## 一次性配置（需要你的 GitHub 账号）

1. 建一个仓库（public / private 都行），例如 `yt-relay`。
2. 把 `.github/workflows/yt-watch.yml` 传上去（保持 `.github/workflows/` 目录结构）。
3. 仓库 **Settings → Actions → General → Workflow permissions** 选 **Read and write permissions**
   （工作流要把抽好的帧 commit 回仓库，本机才能经 `codeload` 取回）。
4. 若要跑 whisper 转写，`transcribe` 传 `true`（CPU 跑 small 模型，10 分钟音视频约 3-8 分钟）。

## 日常用法

### 模式 A：你在浏览器点按钮（**不需要给我任何凭据**）

1. 打开仓库的 **Actions** 页 → 左侧选 `yt-watch` → 右侧 **Run workflow**
2. 填 `url`（YouTube 链接或 11 位视频 ID），可调 `frames` / `start` / `duration` / `quality`
3. 等 2-5 分钟跑完，然后本机执行：

```bash
python3 /mnt/workspace/yt-relay/yt_relay.py fetch --repo <你的账号>/yt-relay
```

帧会落到 `/mnt/workspace/yt-relay/results/frames/`，脚本末尾直接打印 `MEDIA:<路径>`，
复制给 vision 就能让 Agent"看"视频。

### 模式 B：全自动（需要一个 GitHub PAT）

PAT 勾选 `actions:write` + `contents:write`：

```bash
export GH_TOKEN=ghp_xxxx
python3 /mnt/workspace/yt-relay/yt_relay.py run \
  --repo <你的账号>/yt-relay \
  --url "https://www.youtube.com/watch?v=xxxx" \
  --frames 12 --transcribe
```

脚本会自动：触发 → 轮询等待 → 经 `codeload` 回取 → 打印帧路径。

## 参数说明

| 参数 | 默认 | 说明 |
|---|---|---|
| `url` | 必填 | YouTube 链接或 11 位视频 ID |
| `frames` | 12 | 抽多少张关键帧（在取样区间内均匀分布） |
| `start` | 0 | 从第几秒开始取样 |
| `duration` | 0 | 取多少秒（0 = 整片） |
| `quality` | 360 | 最大分辨率；帧统一缩到高 480，够 vision 看 |
| `transcribe` | false | 是否顺带跑 whisper 转写（**无字幕视频的兜底**） |

## 产物（在仓库 `latest/` 目录，本机取回到 `results/`）

- `frames/f001.jpg ...` —— 关键帧（等比缩到高 480）
- `meta.json` —— 视频元信息（标题/时长/上传者等）
- `subs/` —— 有字幕轨时的 vtt
- `transcript.txt` —— 开了 `transcribe` 时的时间戳转写
- `SUMMARY.md` —— 本轮结果清单

## 已知边界（说清楚免得踩）

1. **每次跑会清空上一轮 `latest/`**——仓库工作区只保留最近一次结果，控制体积。
   但 git 历史里二进制帧会累积，跑很多次后仓库会变大（可改用单独分支或定期清历史）。
2. **拿不到视频文件本身**（帧 + 转写是给你"看/读"的）。视频本体留在 runner 上跑完即销毁；
   真要视频文件得另加一个"把 mp4 用 `git lfs`/release 附件带回"的步骤。
3. **whisper 走 CPU**，长视频慢；短片段（配合 `start` / `duration`）更快也更省额度。
4. **私有仓库消耗 Actions 分钟数**（免费 2000 分钟/月）；公开仓库不消耗。
5. **本机仍不能直连 YouTube**——这套方案是"借用跑腿的"，不是"打通了网络"。
   本地 `fetch_yt.sh`（走 Exa）依旧是无字幕视频之外的快速取文本通道。
