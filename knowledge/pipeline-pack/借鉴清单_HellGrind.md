# 借鉴清单 · Higgsfield《Hell Grind》生产档案

来源：官方 Brief（https://higgsfield.ai/@higgsfield.studio/projects/hell-grind ）+ 三份 skill（CINEDANCE / ACTING / LIRA）。第三方镜像 github.com/XucroYuri/higgsfield-hell-grind-opensource 只收 Brief、skill、成本分析；媒体 925GB 不入库。
核对日 2026-09-18。结论：不新增岗位。改 5.2 提示词编译、7a 画面描述、6.1 首帧规则、9 声音岗；资产岗加验收。

## 他们是什么

| 项 | 数字 |
|---|---|
| 成片 | 95 分钟写实电影，15 人，资产备好后 14 天生成 |
| 生成量 | 38,482 批 / 115,449 条；Seedance 2.0 占 88% 条数、99% 成本 |
| 采纳 | 每批中位 4 变体取 1 → 约 3–4 次生成换 1 次采纳 |
| 成本大头 | 15 秒 / 1080p 长镜（23,742 批是 15s） |
| 模型分工 | 视频+语音 Seedance 2.0；脸和场景 Soul Cinema；点改 Nano Banana Pro / Seedream 4.5；画内文字、道具、反打空镜 GPT Image 2 |
| 提示词 | 固定骨架 15 段（SCENE CONTEXT → … → POSITIVE CONSTRAINTS），3,000–4,000 词，英文；描述词和 Style Prefix 是常量 |
| 首帧 | **没有图片首帧**。文字写死第 1 格 + 第一秒全景定位 + 资产参考图 |
| 归档 | 每场一个目录：`prompts/00001_<job_set>.txt` 逐版落盘 + `Assets/outputs/<job_id>/` + `Regenerations/` |

和我们同一条路：Seedance 一镜一任务、资产先锁、提示词是合同。不同：他们写实 / 10–15 秒多拍长镜 / 文字首帧；我们 CG / 2–4 秒快切 / 图片锁首帧。

## 要借鉴

| 他们的做法 | 收成什么 | 进哪一岗 |
|---|---|---|
| 对白只在 AUDIO 块：声线描述逐字 → 引号台词 → 动作 → 表情；没词的人完全不出声，半笑是表情不是声音；全片语音直接用 Seedance 唇同步不重录 | `speech_mode=seedance_native`、`voice_card`、`audio_block`；中文工作轨原声唇同步 | 5.2、9 声音 |
| 写行为不写情绪：objective / obstacle / tactic，手上的事，肌肉；「脸上演情绪」= 坏演技第一条；眼先到位头后转、眨眼、眼神光；反应在对方话没说完就开始；情绪有惯性拖进下一镜 | `acting{want,hide,business,muscle,change}`；形容词情绪告警 `acting_adjective`；15 条坏演技图谱当自检 | 7a 画面描述、5.2 |
| 复杂动作不放中间，开头就在进行中；走近门是另一镜 | 首帧 = 动作起点状态（可已起手，禁结果）；motion 从 0.0s 就动；ACTION TIMING 按秒两拍 | 6.1、5.2、`still_t0.py` |
| GEO SPATIAL LAYOUT：一场一份文字平面图（地标、画左/画右、米数、机位在哪一侧、永不过的线、光从哪来），同场每镜原样粘贴 | `sets.json.geo_zh` → `geo_layout` 前置进静帧和视频提示词 | 5.2、分镜 |
| 描述词 descriptor 逐字进每条提示词，永不缩写；不写年龄 | `descriptor` 每人一句 + 「100% 以参考图为准」 | 资产、5.2 |
| 只写肯定句；禁词词典（dark→low key） | 编译出的 motion 无「禁止/不要」；`ban_dictionary` | 5.2 |
| 密度控制：身份、站位、首帧、视线、手、道具、时序、光、物理写细，装饰词砍掉 | 中文提示词 ≤500 字软闸，先砍装饰词 | 5.2 |
| 每张参考图点名角色；场景图「不作首帧、不继承构图角度色调」 | 已有 `[图N]` 写法，表述对齐 | 6.1 |
| 锁前压力测试：10 张不同姿势不同光、同框、真实场景光，10/10 认得出才锁；错在描述不在模型 | Gate B 加 `stress_test` | 资产 |
| 角色表正面全身无头；3/4 大像；灰底平光不烤电影感 | 试一张无头面板防中远景偷小脸 | 资产 |
| 点改用蒙版合回原图；图不整张过第二次模型 | Codex edit 只改一件事，合回 master | 资产、6.1 |
| 场景 3/4 出图；每场一个锚点物；一套光逻辑；反打空镜 = 空场景走场视频截图再过纹理 | `scenes/<id>/reverse.jpg` 资产步骤 | 资产 |
| 门槛过场：两张场景资产同进一镜，门洞光比反差解释调色变化 | 走廊→七线一类过场 | 分镜 |
| 人群一个资产 + 明写「20+」；巨物写尺度锚 | 七线工人 | 资产、5.2 |
| 10–15 次不成就拆镜/删动作/换角度，不改词；一次改一行全进日志 | 已有（Trigger 次数上限、failure_ticket） | 统筹 |
| 剪辑与生成并行，每条首尾各剪 0.5 秒；生成只出环境声，音乐后期；连续环境床粘碎镜 | 已有（4s 渲剪成 2–4s、path A 音效床） | 剪辑、声音 |

## 不要借鉴

- Photoreal Style Prefix「no 3D render」——方舟拦真人脸，我们锁 CG。
- Soul ID / Nano Banana / GPT Image 2 路由——平台绑死。
- 10–15 秒多拍长镜、「第一秒全景 + hm」——那是没有图片首帧的补丁，我们图片锁首帧更强。
- 1080p / 15s std——他们成本的来源；我们 Mini 720p 4s。
- 3,000–4,000 词提示词——方舟中文建议 ≤500 字。
- CINEDANCE 模板里的 age——Brief 后来明说写年龄触发未成年过滤。
- 把镜像仓库当资料库——有价值的只是 Brief + 三份 skill（约 90KB）。

## 真人脸拦截：他们怎么过的

不是绕过，是平台授信。拦截规则在字节模型侧（`InputImageSensitiveContentDetected.PrivacyInformation`），Higgsfield 也说「检测在 Seedance 2.0 那边」。他们的脸由平台自家 Soul Cinema 生成，平台信任本账号内自家模型产物。

字节两边对应机制：
- BytePlus ModelArk：同账号 30 天内 Seedance 2.0/2.5 视频、其尾帧、Seedream 5.0 lite 文生图的含脸产物可作输入不触发拦截；**原始产物、未二次编辑、不压缩转存**才算。
- 火山方舟：「特定模型生成内容授信 / 隐形数字护照」、公共虚拟人像库（`asset://` 预置合规人脸）、私域虚拟人像库、真人认证入库。

对我们：EP01 25/29 镜走 H3，是因为 Codex（外部）静帧写实就拦。授信要求原图不编辑，和我们 place 缩放、父图链编辑相冲，**不是换模型就完事**。

探针（未采纳）：
1. 方舟 Seedream 5.0 lite 文生一张写实脸 → 原图直接当 `first_frame` → 看 `PrivacyInformation` 是否触发。
2. 私域虚拟人像库入库琳 / 春安 / 波帕 → 首帧含同一张脸是否放行。
3. Seedance 尾帧作下一镜首帧（同机位续吃末帧）是否天然可信。

## 对白与语种

Seedance 2.0 台词写在引号里 + 语种 + 语气即可唇同步。官方支持中/英/日/韩/西/法/德，**无高棉语**。`reference_audio` 可驱动口型，但属多模态参考模式，与 `first_frame` 互斥。

决定：中文工作轨走 Seedance 原声唇同步（圣经的中文导出轨）；高棉语仍是配音 / 字幕轨（Gate F）。H3 fallback 镜没有原声对白。SRT 以后按成片音轨重对时，不再按 +0.6s 估。

## PM 决定（2026-09-18）

1. 改成 Seedance 唇同步，不重录（中文工作轨）。
2. 表演按 Hell Grind 写行为不写情绪；「夸张表情：X」写法废止。
3. 首帧 = 动作起点状态，可已起手；motion 从 0.0s 就在动。

## 落地状态

| 项 | 状态 |
|---|---|
| 5.2 编译：`audio_block` / `voice_card` / `geo_layout` / `descriptor` / 肯定句去重 / ≤500 软闸 / `ban_dictionary` | 已落地：`scripts/director/speech.py`、`prompts.py`、`pipeline.py`；`GEO` 从 `sets.json.geo_zh`，卡片从 `01-bible/CHARACTERS.md`（抄本 `.pipeline/voice_cards.json`） |
| 对白开关 | 表级 `speech_mode`；每镜 `dialogue_delivery`：`on_camera` 原声 / `post` 退 `post_dub`；全 `post` 的老表按 `post_dub`，混表编包列出退出镜 |
| 7a：`acting{want,hide,business,muscle,change}`（7a 逐字段覆盖表行）+ `acting_adjective` 告警（扫 `one_paragraph` / `still_*` / `micro_expression` / `acting` 可见格）+ 15 条坏演技图谱 | 已落地：`acting.py`、`frame_desc.py`、`07a_画面描述.md` |
| 6.1：`still_t0.py` 起点状态（`ONSET_OK`）；motion 从 0.0s 两拍 | 已落地；`AGENTS.md`、`07_关键帧_6.1.md` 同步 |
| 010 EP01-v2 67 镜重编包 | 已重编：67/67 `audio_block`，51 镜原声 `on_camera`，16 镜静音，59 镜 `acting`，0 形容词告警，0 否定句；首帧 67 / 尾帧 21 未动；22 镜 501–597 字超软闸（GEO + 声线卡 + 多人表演），待 PM 定是否压 GEO |
| 知识层 / 顶层文档 / 模板（30 文件）| 已改：playbook、cutting、motion、07、07a、06(5.2)、04、09、03、交接字段表、vo、seedance 2.0/2.5 种子、adopted-skills、quality、VIDEO、DUBBING、DIRECTOR、PIPELINE、`_template` / `templates`、岗位说明书声音岗 |
| 测试 | `test_speech_acting.py` 30 条（含 4 条对齐测试）；全套 267 条只剩 2 条改动前就挂的（GPU 环境、旧 state 规则） |
| 资产岗：压力测试、无头面板、蒙版合回、反打走场 | 文档规则；`place_codex_asset.py` 无 `headless` / `reverse` 槽位，暂手工落盘 |
| 方舟授信 / 虚拟人像库探针 | 未做 |
| 下一步 | `05-shots/ep01-v2/` 已有 9-14/15 Grok 手出的 67 条无 sidecar 旧片，原声重渲要 `--force`（先归档到 `archive-before-force/`） |
