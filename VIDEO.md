# Gate E：出片

本文件是 **API 路线**（`render_shots.py` 自动吃末帧）。  
在 grok.com/imagine 画布上手工出图出片走 **`GROK-CANVAS.md`**，导演层规则完全一致，只换执行工具。

正式成片默认 **Seedance 2.0 Mini 720p**（见下「出片」一节）；中文对白走 **Seedance 原声唇同步**（`speech_mode=seedance_native`，见「对白」一节），BGM、高棉语后期。  
MiniMax 路线保留：**Hailuo 2.3 Fast 无声图生视频**打普通镜，**H3 只打精品镜 / 人脸拦截 fallback**（近景脸、关键仪式、必须卡环境声的动作），每集最多 3 镜。这两条路都没有原声对白。

关掉角色配音 **不会让 H3 更便宜**（按输出秒数计费）。要省钱就走 Fast 无声，不要为背景音去买 H3。

## 路由

| `shots.json` 的 `tier` | 模型 | 大约 6 秒 768P |
|---|---|---|
| `fast`（默认） | `MiniMax-Hailuo-2.3-Fast` | **$0.19**，无声 |
| `h3` | `MiniMax-H3` | 官方约 **$0.48**；优云智算 CompShare 按积分（768P **10 积分/秒**）。仍不把人声当配音轨 |

H3 提交前必须有该镜 `characters` 的 `face.jpg` / `master.jpg`。缺文件则脚本拒绝跑。

- **官方 MiniMax H3**：硬首帧 I2V，或首尾帧。官方合同与 CompShare 一样——**首帧不能和 reference_image 混用**。`minimax_h3.py` 会丢掉参考图，身份靠 6.1 父图链。768P 刊例 ¥0.50/秒，2K ¥0.80/秒；图生 5 张内不收输入费。
- **优云智算 CompShare**：同一套 MiniMax-H3，分辨率目前只有 **768P**，时长 4–15 秒。密钥前缀 `sk-ml-`，接口 `https://cp.compshare.cn/minimax/v2/video_generation`。设了 `COMPSHARE_API_KEY` 时，**只有 auto 的 h3 档**走 CompShare；`--backend minimax` / `--backend h3` 仍走官方。首帧必须是公网 URL（data URL 会卡住）；默认推到公开仓库 `COMPSHARE_IMAGE_REPO`，用 jsDelivr 给优云拉。

## 先别急着租 4090

H3 是开源全模态视频模型，官方也提供按量 API。

| 路线 | 适合 | 注意 |
|---|---|---|
| **优云智算 CompShare `MiniMax-H3`** | 国内积分/免费额度先跑精品镜 | 768P only。首帧 I2V，不能同时塞角色参考图。失败积分退回 |
| **官方 API `MiniMax-H3`** | 要把整集跑通 | 不占显卡。硬首帧或首尾帧，4–15 秒，768P / 2K。不能同时塞角色参考图 |
| **云端 4090 自建** | 要大量出片、不想按秒付 API | 单张 24GB 4090 很紧。实测 4090D 48G / Pro 5000 都吃力；竖屏 9:16、6–10 秒更吃显存。至少按 **双 4090** 或 **48GB+** 估，不要按一张 24G 4090 当稳定产能 |

## Seedance 2.0 Mini（火山方舟）

这是云端图生视频，不是本机 GPU。接到导演台现有「一镜一任务」出片口。**一镜一任务 = 一镜一机位**：默认不片内切（`max_internal_cuts=0`）。模型能听「N秒切到…」，本仓库不把这种句子编进 motion。

1. 分镜设计 / 说明书仍在本地写，不把整集塞给模型。
2. 6.1 锁首帧后，6.2 按镜 POST /contents/generations/tasks。
3. role=first_frame 必带；有设计尾帧才加 last_frame；角色/场景参考挂在首帧外面。
4. 禁止文生视频进 05-shots/。
5. motion 写本机位怎么动；落幅是这个机位的结束状态，不是下一镜的机位。首帧是动作起点状态（可已起手），motion 从 0.0s 接着动，ACTION TIMING 按秒两拍，只写肯定句；段首粘本场 `geo_layout`。
6. 对白只在 `audio_block`（见下「对白」一节），不进动作句。

```bash
export ARK_API_KEY=你的方舟密钥
export ARK_SEEDANCE_MODEL=控制台里的推理接入点 ID   # 没有接入点时先用 doubao-seedance-2-0-mini-260615
python3 scripts/render_shots.py --prod productions/009-siem-reap --backend seedance --only SH001
```

导演台有 ARK_API_KEY 时，派出按钮走 Seedance，不再要求 LOCAL_H3_BASE。没密钥仍停在 queued，不假装成功。人脸拦截探针仍用 480p 最短 4 秒。Mini 不支持 1080p。

## 出片：Seedance Mini 720p → 人脸拦截才 H3 768p → 本地缩到 1280×720

正式成片只走这条。`05-shots/smoke*` 试镜不走 fallback，也不写进正式 `05-shots/SHxxx.mp4`。

1. **主路径：** Seedance 2.0 Mini **720p**（`1280×720`，`ARK_RESOLUTION=720p`）。
2. **Fallback：** 仅当 create 被判成人脸拦截（`InputImageSensitiveContentDetected.PrivacyInformation` / `*.PrivacyInformation`，`check_seedance_frame.classify_create` = FAIL）。**这一镜**改走 **官方 MiniMax-H3 768p**（`minimax_h3.py`，不走 CompShare）。
3. **不是 fallback：** 配额、超时、提示词风控、payload 错误、任务已创建后的 poll 失败。这些回 Seedance 修/重试。
4. H3 回片后 **本机 ffmpeg** `scale=1280:720:flags=lanczos`，aac stereo，再晋升正式 `05-shots/SHxxx.mp4`。768p 只留在 `05-shots/h3-staging/`。不调模型 API 缩放，不调色。
5. 成片记录：`backend=minimax_h3`，`fallback_from=seedance`，`scaled_to=1280x720`（`SHxxx.mp4.clip.json`）。
6. 缺 `MINIMAX_API_KEY` 时该镜明确失败：`face-blocked, no H3 key`。不静默跳过。

H3 可能也拦写实人脸（以后 live probe，不挡方案）。Seedance `generate_audio` 和 H3 环境声拼接时应对齐 aac stereo。`assemble.sh` 仍 `-c copy`，因此正式镜必须已经是同一尺寸。

```bash
# 正式 6.2（人脸拦截自动 H3）
python3 scripts/render_seedance_packages.py --prod productions/010-gongpai --only SH010

# 已知该镜已被脸拦、跳过 Seedance
python3 scripts/render_seedance_packages.py --prod productions/010-gongpai --only SH010 --h3-fallback
```

秒数只校验不夹紧：镜头表写了 4–15 以外的秒数，`seedance_ark.py` / `compshare_h3.py` 直接报错「改分镜表，不替人改」，不静默改成 4 或 15。

真人脸拦没有官方预检接口（内容安全 ImageModeration / `+understand` / `doctor +verify-origin` 都不是这套 `PrivacyInformation` 分类器）。出图后跑 `python3 scripts/check_seedance_frame.py --prod productions/<slug> --image 04-frames/SHxxx.jpg`：只发 first_frame、480p、最短 4 秒；**submit 400 就是检查**（无 task id，审核失败不收费）；200 立刻 DELETE（仅 queued 能取消，已 running 的 4s 480p 仍可能出片计费）。1–2 秒非法，会被参数拒，测不到脸。

### 拦截来源与方舟授信（探针，未采纳）

拦截在字节模型侧，不是提示词问题。Higgsfield《Hell Grind》写实脸能过，是因为脸由平台自家模型（Soul Cinema）生成，平台信任本账号内自家模型的产物。字节两边对应：BytePlus ModelArk 明说**同账号、30 天内、Seedance 2.0 / 2.5 视频及其尾帧、Seedream 5.0 lite 文生图的原始产物**可作输入不触发拦截，**压缩、编辑过就不算**；火山方舟叫「特定模型生成内容授信 / 隐形数字护照」，另有公共虚拟人像库（`asset://`）、私域虚拟人像库、真人认证入库。

我们的静帧是 Codex 外部生成，写实即拦；`place_codex_frame.py` 缩放和父图链 edit 也破授信。所以**主路径仍是 CG 画风 + 人脸拦截才 H3**，下面只是探针，谁跑了把结果写回 `knowledge/model-notes/seedance_2_0.md` 种子表：

1. 方舟 Seedream 5.0 lite 文生一张写实脸，原图不动直接当 `first_frame` → 看 `PrivacyInformation` 是否触发。
2. 私域虚拟人像库入库一个角色 → 首帧含同一张脸是否放行。
3. Seedance 出片的尾帧直接作下一镜 `first_frame`（同机位续吃末帧）→ 是否天然可信。

三条都过了再谈换路由；一条不过就维持现状。

**待实测**：方舟文档称首帧图生视频 / 首尾帧 / 多模态参考三种模式互斥；`seedance_ark.py` 目前在 i2v 同时发 `first_frame` + `reference_image`，可能被拒（400）或参考图被忽略。冒烟视频派出时验证（见 `productions/010-gongpai/04-frames/smoke-test.md`「顺带要验的」）；若互斥，改为「硬首帧 = 不带身份参考（身份靠 6.1 父图链），参考模式 = 软首帧，不进 05-shots/」。


都市短剧（`002-sophea-tent`）9 镜、58 秒。神话旁白集可以更长。先用 API 验证脸会不会漂，再决定要不要养机器。积分空了就停，不要用 Ken Burns 冒充 H3。

## 对白：Seedance 原声（中文工作轨）

2026-09-18 起，中文工作轨的对白由 Seedance 自己说、自己对口型，不再后期重录。生成包 `speech_mode=seedance_native`（默认），提交 `generate_audio=true`。

- 台词只在 `audio_block` 里，顺序固定：`voice_card` 逐字 → 「引号台词」+ 语种 + 语气（怎么说，不是什么心情）→ 只说这一句 → 不说话的人嘴闭着 → 环境声、无音乐、无字幕。说话时的动作和表情（肌肉）在紧跟的【表演】句里，不进 `audio_block`；动作句里不出现台词。
- 每镜开关是 `dialogue_delivery`：`on_camera` = 模型说这句（原声），`post` = 后期配。原声表（`speech_mode=seedance_native`，或目标模型能唇同步且表未声明）里没写的有词镜默认 `on_camera`；写了 `post` 的镜单独退成 `post_dub`，编包会列出来。全表都是 `post` 的老表按 `post_dub` 处理，不报。
- 块尾一句写死：每人只说引号里的那句话，不说话的人**嘴闭着**；只有环境声，**没有音乐，没有字幕**。不写这句模型会加碎话、哼唱和配乐。
- 原生语种：中 / 英 / 日 / 韩 / 西 / 法 / 德。**没有高棉语**——高棉语仍是配音 / 字幕轨（Gate F，`DUBBING.md`）。`reference_audio` 能驱动口型，但它属多模态参考模式，与 `first_frame` 互斥；不为口型丢掉硬首帧。
- 中文提示词 ≤500 字软闸，只写肯定句（否定句被忽略或反做，`ban_dictionary` 翻成正向替代）。
- **H3 fallback 镜没有原声**：被脸拦改走 H3 的那一镜，这句对白回后期叠声（该镜 `speech_mode=post_dub`），声音岗按 `voice_card` 重录该句。Hailuo Fast 同理。
- 声音岗只清理原声（降噪、统一音色、放进空间），核对等于原句后才算成品；即兴碎话、自带音乐不进成片。
- `assemble.sh` 仍 `-c copy`：原声镜和 H3 镜拼接前对齐 aac stereo、同尺寸。

## 万相 3.0（阿里云百炼）

这是云端图生视频，不是本机 GPU。北京地域，模型 `wan3.0-video`（可改 `wan3.0-video-prime`）。硬首帧 / 首尾帧，ratio 用 adaptive。**首帧不能和 reference_image 混用**，身份靠 6.1 父图链。提示词中文。默认关声音、关 prompt 改写。时长 2–30 秒，秒数只校验不夹紧。试镜写到 `05-shots/smoke-wan/`，不覆盖正式成片。

默认出片路由不因为配了百炼密钥就改走万相。要测时显式指定。

```bash
# 是否已配密钥（不发任务）
python3 scripts/video_backends/wan3.py --check

# 010-gongpai 试镜：SH027 硬首帧，写到 05-shots/smoke-wan/
python3 scripts/video_backends/wan3.py --prod productions/010-gongpai --shot SH027 --dry-run
python3 scripts/video_backends/wan3.py --prod productions/010-gongpai --shot SH027

# 或走总入口
python3 scripts/render_shots.py --prod productions/010-gongpai --backend wan --only SH027 --video-dir 05-shots/smoke-wan --skip-assemble
```

分辨率 480P / 720P / 1080P。本仓库测试默认 720P。计费按百炼控制台，开关声音同价。

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
cp .env.example .env   # 填 MINIMAX_API_KEY；国内账号改 MINIMAX_BASE_URL
pip install -r requirements.txt
set -a && source .env && set +a

# 官方 H3 是否已配密钥（不发任务）
python3 scripts/video_backends/minimax_h3.py --check

# 010-gongpai 试镜：SH027 硬首帧，写到 05-shots/smoke-h3/，不动正式 05-shots/SH027.mp4
python3 scripts/video_backends/minimax_h3.py --prod productions/010-gongpai --shot SH027 --dry-run
python3 scripts/video_backends/minimax_h3.py --prod productions/010-gongpai --shot SH027

# 查 CompShare H3 积分
python3 scripts/video_backends/compshare_h3.py --balance

# 按 shots.json 的 tier 自动分流（有 COMPSHARE_API_KEY 时 auto 的 h3 档走优云智算）
python3 scripts/render_shots.py --prod productions/001-wip

# 只重跑喝海（H3 精品镜）
python3 scripts/render_shots.py --prod productions/001-wip --only SH010

# 强制指定后端
python3 scripts/render_shots.py --prod productions/001-wip --backend minimax --only SH027
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
{ "image_b64": "...", "prompt": "...", "duration": 6, "aspect": "16:9", "mode": "i2v|flf|r2v", "refs_b64": [], "last_frame_b64": null }
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

每镜时长已写在该集 `shots.json` / 镜头表。单集时长等于各镜之和。H3 支持 4–15 秒整数。画幅跟本剧 confirm 走，默认 16:9。


## Ken Burns 不是成片

`scripts/stills-to-shots.sh` 已隔离到 `scripts/_disabled/`。导演台和 `assemble.sh` 拒绝 `*kenburns*` / `*still-pass*` / `*animatic*` 进入 `06-export/`。

静帧 animatic（`scripts/animatic.py`，`03-storyboard/animatic/epNN.animatic.mp4`）是审片工具：首帧按镜头表秒数切着看节奏，不是成片路径，不进 `05-shots/`、`06-export/`。
