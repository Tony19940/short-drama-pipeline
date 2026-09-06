# Gate E：出片

本文件是 **API 路线**（`render_shots.py` 自动吃末帧）。  
在 grok.com/imagine 画布上手工出图出片走 **`GROK-CANVAS.md`**，导演层规则完全一致，只换执行工具。

默认 **Hailuo 2.3 Fast 无声图生视频**，后期叠 BGM / 环境声 / 旁白。  
**H3 只打精品镜**（近景脸、关键仪式、必须卡环境声的动作），每集最多 3 镜。

关掉角色配音 **不会让 H3 更便宜**（按输出秒数计费）。要省钱就走 Fast 无声，不要为背景音去买 H3。

## 路由

| `shots.json` 的 `tier` | 模型 | 大约 6 秒 768P |
|---|---|---|
| `fast`（默认） | `MiniMax-Hailuo-2.3-Fast` | **$0.19**，无声 |
| `h3` | `MiniMax-H3` | 官方约 **$0.48**；优云智算 CompShare 按积分（768P **10 积分/秒**）。仍不把人声当配音轨 |

H3 提交前必须有该镜 `characters` 的 `face.jpg` / `master.jpg`。缺文件则脚本拒绝跑。

- **官方 MiniMax**：首帧 + 角色参考图（`reference_image`）。
- **优云智算 CompShare**：同一套 MiniMax-H3，但平台规定 **首帧不能和参考图混用**。脚本仍校验角色主图存在，提交时只带锁定首帧。密钥前缀 `sk-ml-`，接口 `https://cp.compshare.cn/minimax/v2/video_generation`，分辨率目前只有 **768P**，时长 4–15 秒。设了 `COMPSHARE_API_KEY` 时，`auto` / `h3` 走 CompShare。首帧必须是公网 URL（data URL 会卡住）；默认推到公开仓库 `COMPSHARE_IMAGE_REPO`，用 jsDelivr 给优云拉。

## 先别急着租 4090

H3 是开源全模态视频模型，官方也提供按量 API。

| 路线 | 适合 | 注意 |
|---|---|---|
| **优云智算 CompShare `MiniMax-H3`** | 国内积分/免费额度先跑精品镜 | 768P only。首帧 I2V，不能同时塞角色参考图。失败积分退回 |
| **官方 API `MiniMax-H3`** | 要把整集跑通 | 不占显卡。图生视频：首帧 + 角色参考图，4–15 秒，768P / 2K |
| **云端 4090 自建** | 要大量出片、不想按秒付 API | 单张 24GB 4090 很紧。实测 4090D 48G / Pro 5000 都吃力；竖屏 9:16、6–10 秒更吃显存。至少按 **双 4090** 或 **48GB+** 估，不要按一张 24G 4090 当稳定产能 |

## Seedance 2.0 Mini（火山方舟）

这是云端图生视频，不是本机 GPU。接到导演台现有「一镜一任务」出片口：

1. 分镜设计 / 说明书仍在本地写，不把整集塞给模型。
2. 6.1 锁首帧后，6.2 按镜 POST /contents/generations/tasks。
3. role=first_frame 必带；有设计尾帧才加 last_frame；角色/场景参考挂在首帧外面。
4. 禁止文生视频进 05-shots/。

```bash
export ARK_API_KEY=你的方舟密钥
export ARK_SEEDANCE_MODEL=控制台里的推理接入点 ID   # 没有接入点时先用 doubao-seedance-2-0-mini-260615
python3 scripts/render_shots.py --prod productions/009-siem-reap --backend seedance --only SH001
```

导演台有 ARK_API_KEY 时，派出按钮走 Seedance，不再要求 LOCAL_H3_BASE。没密钥仍停在 queued，不假装成功。测试默认 480p 省成本；正式再升 720p。Mini 不支持 1080p。


都市短剧（`002-sophea-tent`）9 镜、58 秒。神话旁白集可以更长。先用 API 验证脸会不会漂，再决定要不要养机器。积分空了就停，不要用 Ken Burns 冒充 H3。

## 接到本工程的位置

```
04-frames/SH00N.jpg  +  shots.json 里编译后的 video_prompt
        │
        ▼
 scripts/render_shots.py          # 首帧 FL2VA；同机位续吃末帧；设计尾帧；参考外挂
        │
        ▼
 05-shots/SH00N.mp4  →  assemble.sh  →  06-export/ep01.mp4
```

不重做 Gate A–D。坏一镜只重跑那一镜：`--only SH010`。

## 用法

```bash
cd "vibe coding/short-drama-pipeline"
cp .env.example .env   # 填 COMPSHARE_API_KEY 或 MINIMAX_API_KEY
pip install -r requirements.txt
set -a && source .env && set +a

# 查 CompShare H3 积分
python3 scripts/video_backends/compshare_h3.py --balance

# 按 shots.json 的 tier 自动分流（有 COMPSHARE_API_KEY 时 h3 走优云智算）
python3 scripts/render_shots.py --prod productions/001-wip

# 只重跑喝海（H3 精品镜）
python3 scripts/render_shots.py --prod productions/001-wip --only SH010

# 强制指定后端
python3 scripts/render_shots.py --prod productions/001-wip --backend compshare --only SH004
python3 scripts/render_shots.py --prod productions/001-wip --backend hailuo

# 4090 盒子起来之后
export LOCAL_H3_BASE=http://你的机器:8000
python3 scripts/render_shots.py --prod productions/001-wip --backend local
```

国内 MiniMax 官方账号把 `MINIMAX_BASE_URL` 改成 `https://api.minimaxi.com`。

## 自建 4090 要对接的接口

`local` 后端认这个合同。你在 GPU 上用官方推理容器或 ComfyUI 包一层即可：

```
POST /v1/i2v
{ "image_b64": "...", "prompt": "...", "duration": 6, "aspect": "9:16", "mode": "i2v|flf|r2v", "refs_b64": [], "last_frame_b64": null }
→ { "task_id": "..." }

换机器时拷 `scripts/video_backends/runpod_i2v_server.py`。合同是：

1. `image_b64` = 锁定首帧（设计静帧，或同机位续的上一镜真末帧）
2. `last_frame_b64` = 设计尾帧，不是抽出的 `-last.jpg`
3. `refs_b64` = 身份/场景参考，挂在首帧外面
4. `refs_b64` 走 ReferenceToVideo 外挂；采样仍锁 `image_b64`。不许把参考图当成新的第 0 秒

GET /v1/i2v/{task_id}
→ { "status": "queued|running|succeeded|failed", "url": "http://.../out.mp4" }
```

如果官方镜像已经是 MiniMax v2（`/v2/video_generation`），不用 `local`，直接：

```bash
export MINIMAX_BASE_URL=http://你的机器:8000
python3 scripts/render_shots.py --prod productions/001-wip --backend minimax
```

## 和分镜的对应

每镜时长已写在 `productions/001-wip/03-storyboard/shots.json`。H3 支持 4–15 秒整数，6 和 10 都合法。画幅跟首帧走，我们的首帧是 9:16。


## Ken Burns 不是成片

`scripts/stills-to-shots.sh` 已隔离到 `scripts/_disabled/`。导演台和 `assemble.sh` 拒绝 `*kenburns*` / `*still-pass*` 进入 `06-export/`。
