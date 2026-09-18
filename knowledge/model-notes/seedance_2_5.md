# 模型经验 · Seedance 2.5（火山方舟 doubao-seedance-2-5）

核对日 2026-09-09。事实源：本账号 `arkcli models get doubao-seedance-2-5-260628` / `models search` / `pricing models`；创建任务契约见方舟「创建视频生成任务」与虚拟人像库文档。未付费出片。`+gen --dry-run` 只预览本地 payload。

QC 回写只保留下面 `## 种子`。本页 `## 能力` 是编包合同，回写后从 git 恢复。

## 种子

三列：现象 / 原因 / 处理。跨模型的已知坏法，先于 QC 记录。

| 现象 | 原因 | 处理 |
|---|---|---|
| HTTP 400：first_frame 和 reference_image 同在 | 首帧 / 首尾帧 / 多模态参考三种模式互斥 | 硬首帧只发 first_frame；身份靠 6.1 父图链。要多参考就走 reference_image，用提示词写「首帧为图片N」，不要 role=first_frame |
| 首帧任务传 ratio=16:9 被拒 | 2.5 首帧、首尾帧、编辑、延长只许 ratio=adaptive | 包里仍写画幅 16:9；提交改 adaptive，让输出跟首帧像素走 |
| 默认定长或超 15 秒 | 2.5 duration 默认 -1，上限 30；2.0 上限 15 | 本集按 4–15 整数编。不要编 -1。编辑任务才必须 -1 |
| 成片里出现即兴碎话、音乐、不说话的人张嘴 | generate_audio 默认 true，提示词没写 audio_block 就由模型自由发挥 | 中文工作轨走原声唇同步（speech_mode=seedance_native），audio_block 写明每人只说引号里的话、不说话的人嘴闭着、只有环境声没有音乐没有字幕；无对白镜也写环境声句 |
| 参考图被拒（真人人脸） | 2.0 / 2.5 都不接受直接上传真人人脸参考 | 本剧锁数字电影 CG；真人参考改虚拟人像库 `asset://` 或已授权素材 |

## 能力

### 本账号可见 ID

当前 profile `platform_cn-beijing_accountwide`。`arkcli resources list --modality video` 返回 0 条 Endpoint，没有可 `resources resolve` 的 `ep-*`。调用走模型全名，不是接入点。

| 形态 | 值 |
|---|---|
| 族名 / DisplayName | `doubao-seedance-2-5` / `Doubao-Seedance-2.5` |
| 完整 Model ID | `doubao-seedance-2-5-260628` |
| `primary_version` | `260628` |
| lifecycle | `Published` |
| 广场别名 | 搜 `seedance-2.5` / `doubao-seedance` 只命中这一条 2.5。catalog **没有** `seedance-2.5`、`doubao-seedance` 无版本号当 2.5 |
| 国际/镜像枚举 | 部分创建任务文档把海外名写成 `dreamina-seedance-2-5-260628`。本账号 `models search` **未**列出该名，编包不要当可调用 ID |
| 2.5 变体 | catalog **没有** 2.5-fast / 2.5-mini |
| API | `/v3/contents/generations`（异步任务） |
| 并发（本账号） | `create_task_rpm=180`，`concurrent_requests=3` |

2.0 同账号可见：`doubao-seedance-2-0-260128`、`doubao-seedance-2-0-fast-260128`、`doubao-seedance-2-0-mini-260615`。

### 时长 / 分辨率 / 画幅

| 字段 | 2.5（本账号 `supported_params`） | 2.0 系列 |
|---|---|---|
| `duration` | 整数 **4–30** 或 **-1**。默认 **-1**（模型自选）。编辑任务只能 **-1** | 整数 **4–15** 或 **-1**。默认 **5** |
| `frames` | 不支持 | 不支持 |
| `resolution` | `480p` / `720p` / `1080p`，默认 `720p`。不支持 `4k` | 全量：`480p`–`4k`，默认 `720p`。**fast / mini 只有 `480p` / `720p`** |
| `ratio` 枚举 | `16:9` `4:3` `1:1` `3:4` `9:16` `21:9` `adaptive`，默认 `adaptive` | 同枚举，默认 `adaptive` |
| `ratio` 硬约束 | **首帧、首尾帧、编辑、延长只许 `adaptive`**。文生 / 参考生可用固定比。`omni_reference_task_type=auto` 时建议 `adaptive`，否则可能被判成编辑/延长后异步失败 | 创建任务允许显式 `16:9`（本仓库 `seedance_ark.py` 现按首帧像素写 `16:9`） |
| 16:9 像素（文档表） | 480p `864×496`；720p `1280×720` | 同左。2.0 全量另有 1080p `1920×1080`、4K `3840×2160` |
| `output_format` | `mp4` / `mov`，默认 `mp4` | catalog：2.0 **不支持** 该参数（2.5 才有） |
| 帧率 | 输出 24fps | 同 |

部分创建任务像素表把 2.5 的 1080p 标成「不支持」，与本账号 `supported_params` / 1080 计价条目不一致。编包先锁 **720p**；升 1080p 前用一次付费任务确认，不要猜。

本剧 confirm 锁 16:9。2.5 硬首帧路径：**包里 `aspect_ratio=16:9`，提交 `ratio=adaptive`**，首帧文件必须已是 16:9。

### 三种输入模式（互斥）

`content[].role`：`first_frame` | `last_frame` | `reference_image`。另有 `reference_video` / `reference_audio`。

| 模式 | 输入 | 2.5 | 2.0 |
|---|---|---|---|
| 图生-首帧 | 1 张图，`role=first_frame` 或不填 | 有 | 有 |
| 图生-首尾帧 | 正好 2 张，`first_frame` + `last_frame` | 有 | 有 |
| 多模态参考 | 只许 `reference_*`，**不能**再带 first/last | 图 1–30；视频 0–10（单段 2–30s，合计 ≤30s，单文件 ≤200MB）；音频 0–10（单段 2–30s，合计 ≤30s）。**可以只传音频** | 图 1–9；视频 0–3（单段 2–15s，合计 ≤15s，单文件 ≤50MB）；音频 0–3（单段 2–15s，合计 ≤15s）。**不能只传音频** |

官方约定：三种模式不可混用。同传会 400，不会静默丢掉一边。参考模式若要「像首帧」，用提示词写「首帧为图片N / @imageN」，不要 `role=first_frame`。

单张图：宽高比 (0.4, 2.5)、边长 300–6000px、&lt;30MB；格式 jpeg/png/webp/bmp/tiff/gif，2.x 另加 heic/heif。请求体 ≤64MB。

本仓库现状：`seedance_ark.py` 在 **i2v 同时发 `first_frame` + `reference_image`**；flf 已丢掉 refs。这和官方互斥冲突。`VIDEO.md` 已标待实测。编包不要指望「硬首帧 + 护照图」能过 2.5。

### 2.5 专有：`omni_reference_task_type`

枚举：`auto`（默认）/ `reference` / `edit` / `extend`。2.0 **不支持**。

| 值 | 约束 |
|---|---|
| `auto` | 模型自判。建议 `ratio=adaptive`、`duration=-1`，以免被判成编辑/延长后异步报错 |
| `reference` | `ratio` / `duration` 无额外限制（仍受 4–30） |
| `edit` | 必须有 `reference_video`（4–30s）；`ratio=adaptive`；`duration=-1` |
| `extend` | 必须有 `reference_video`；`ratio=adaptive`；`duration` 无额外限制 |

本流水线成片禁止文生、禁止纯参考进 `05-shots/`。6.2 的 `video_extend` 在 2.5 上应对 `extend` + `reference_video`，**不要**丢给 `auto`。

### 音频 / 对白 / 口型

- `generate_audio`：支持，默认 **true**。true 时模型按提示词和画面出人声、音效、BGM。对白放中文引号「」里。输出单声道。
- `camera_fixed`：2.5 / 2.0 **都不支持**。固定机位写进 `motion_prompt`，不要当 API 开关。
- `draft`：2.5 / 2.0 **都不支持**。
- `seed`：2.x catalog 标不支持。
- 本剧（2026-09-18 起）：中文工作轨 `speech_mode=seedance_native`，提交 `generate_audio=true`，台词放「」里 + 语种 + 语气，走 `audio_block`（声线卡 → 台词 + 语种 + 语气 → 只说这一句 → 不说话的人嘴闭着 → 环境声；动作和表情在【表演】句）。原生中 / 英 / 日 / 韩 / 西 / 法 / 德，**无高棉语**，高棉语仍 Gate F。`reference_audio` 与 `first_frame` 互斥，不为口型丢硬首帧。H3 fallback 镜没有原声。

### 片内切 / 多镜头

API **没有** `internal_cuts` 或「最多切几次」枚举。多镜头是提示词行为。硬首帧 I2V 仍是一条连续动作。本仓库默认 **一镜一机位**，`max_internal_cuts=0`，不把「N秒时切到…」编进 motion。要开片内切是未来某剧的 opt-in。

### 提示词

- 2.0 / 2.5 都支持中英文。2.5 另列西/印尼/葡/日/马/泰/阿/越/韩。2.0 另列西/印尼/葡/日。
- 建议：中文 ≤500 字，英文 ≤1000 词。超长会丢细节。不是硬 400。
- 本仓库编包：`prompt_language=zh`。`image_prompt` 给 6.1 静帧；`motion_prompt` 给 6.2 起幅→动作→落幅。参考模式才用「图片N / @imageN」。

### 运镜

无运镜枚举。`camera_fixed` 不可用。本仓库 `allowed_moves` / `forbidden_moves` 仍是屋规（禁 orbit / drone / crash_zoom / whip_pan）。2.5 不会多开这些 API。

### 编包字段对照

| 包字段 | 2.0 | 2.5 | 010 第 01 集 |
|---|---|---|---|
| `duration_sec` | 4–15 整数 | 4–30 整数；不要编 `-1` | 继续 4–15，一份表两代都能提 |
| `aspect_ratio` | 可写 `16:9`，提交也可 `16:9` | 包里仍写 `16:9`；**硬首帧提交必须 `adaptive`** | 首帧文件锁 16:9 |
| `image_prompt` | 中文静帧；`[图N]` 只服务 6.1 | 同 | 不改语法 |
| `motion` | 中文动作；默认不写片内切 | 同；可写更长段落但本集不必 | 对白写「后期另叠」 |
| `refs` / `asset_refs` | 参考模式最多 9 张；**不能和 first/last 同发** | 参考模式最多 30 张；互斥相同 | 硬首帧：refs 不进 Ark content |
| `audio` / `generate_audio` | 默认 true；本剧开，对白走 `audio_block` | 同 | 开（`speech_mode=seedance_native`） |
| `gen_mode` | `i2v_first` / `flf2v`；`video_extend` 无类型字段 | 同上，另加 `omni_reference_task_type` | 不要为 ep01 编 extend |
| `target_model` | `seedance_2_0` | `seedance_2_5` → `doubao-seedance-2-5-260628` | confirm 锁 2.0 |

### 价格（本账号，元 / 千 tokens）

计价文档：https://www.volcengine.com/docs/82379/1544106 。单位是千 tokens。官方估算：token 用量 = (输入视频时长 + 输出视频时长) × 输出宽 × 输出高 × 帧率 / 1024；I2V 无参考视频时输入时长 = 0。准确值以 `usage.completion_tokens` 为准。

| ChargeItem | 官方价卡含义 | 2.5 `Price` | 2.0 `Price` | 2.0-mini `Price` |
|---|---|---|---|---|
| `V2VCompletion` | 含视频输入（480p/720p） | 0.042 | 0.028 | 0.0056（活动至 2026-10-07，原价 0.014） |
| `NV2VCompletion` | 不含视频输入（480p/720p） | 0.070 | 0.046 | 0.0092（活动至 2026-10-07，原价 0.023） |
| `V2V1080Completion` | 含视频输入 1080p | 0.03312（活动至 2026-09-17，原价 0.046） | 0.031 | 无（mini 无 1080） |
| `NV2V1080Completion` | 不含视频输入 1080p | 0.05544（活动至 2026-09-17，原价 0.077） | 0.051 | 无 |
| `V2V4KCompletion` | 含视频输入 4K | 无 | 0.016 | 无 |
| `NV2V4KCompletion` | 不含视频输入 4K | 无 | 0.026 | 无 |

`V2V*` / `NV2V*` 是「含 / 不含视频输入」两档，**不是** `generate_audio` 有声/静音。2.x 价目没有单独的有声/静音 ChargeItem；开关配音不换档。硬首帧 I2V（无参考视频）走不含视频输入（`NV2V*`，单价更高）。本剧开 `generate_audio` 是为中文原声唇同步，和价格无关。2.5 比 2.0 全量贵；默认出片口仍是 **2.0-mini**。2.5 的 `State=Available`，但本账号还没有视频 Endpoint。

### 干跑

`arkcli +gen --dry-run`（未联网、未扣费）预览：

- 2.5：`model=doubao-seedance-2-5-260628`，`duration=4`，`ratio=adaptive`，`resolution=720p`
- 2.0：`model=doubao-seedance-2-0-260128`，`duration=4`，`ratio=16:9`，`resolution=720p`
