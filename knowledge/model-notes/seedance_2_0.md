# 模型经验 · Seedance 2.0（火山方舟 doubao-seedance-2-0 / -fast / -mini）

QC 回写自动生成；只有 `种子` 一节手写，回写时保留。每条：标签 → 结果（项目 镜号，判定）。最新在前，最多 40 条。
拆镜 / 评审 Agent 通过 `target_profile.experience` 读到前 12 条，种子行在前。

- 记录 0 条；近 0 条里 0 条崩，0 条稳。

## 种子

三列：现象 / 原因 / 处理。跨模型的已知坏法，先于 QC 记录。

| 现象 | 原因 | 处理 |
|---|---|---|
| 全片几乎不动 | motion_prompt 里只有外观没有 one_action | 改成起幅→动作→落幅，重跑不加 attempt |
| 人物不像护照 | 身份图没放最前 / 没点名「只锁脸」 | face.jpg 放第一张参考并点名 |
| HTTP 400 | 风控拦词 | 改写提示词再提，原样硬重试不算 attempt |
| HTTP 400 PrivacyInformation | 真人脸拦 | 该镜走官方 H3 768p，本地缩到 1280×720。其它 400 不换模型 |
| 融脸 | 参考图过多 | 先减到父图 + 1 张 face，稳了再加 |
| HTTP 400：first_frame 和 reference_image 同在 | 首帧 / 首尾帧 / 多模态参考三种模式互斥 | i2v 只发 first_frame；身份靠 6.1 父图链。2.5 同一条，见 `seedance_2_5.md` |
| 写实首帧一律 PrivacyInformation，换提示词也拦 | 拦截在字节模型侧，只放行本账号 30 天内自家模型的原始产物（Seedance 2.0 / 2.5 视频、其尾帧、Seedream 5.0 lite 文生图），未编辑、未压缩转存才算；Codex 外部静帧写实即拦，place 缩放和父图链 edit 也破授信 | 保持 CG 画风走主路径。方舟「特定模型生成内容授信 / 隐形数字护照」、公共与私域虚拟人像库、真人认证入库只做探针，不改路由：Seedream 5.0 lite 原图直接当 first_frame；私域人像库入库后首帧含同一张脸；Seedance 尾帧作下一镜首帧 |
| 不说话的人张嘴、模型加碎话、语种跑偏、出音乐 | 台词没放引号里，没写语种和语气；没声明别人只说引号里的话 | audio_block 顺序：声线卡逐字 → 「引号台词」+ 语种 + 语气 → 只说这一句 → 不说话的人嘴闭着 → 只有环境声没有音乐没有字幕；说话时的动作和表情放紧跟的【表演】句。原生中 / 英 / 日 / 韩 / 西 / 法 / 德，没有高棉语，高棉语走 Gate F |
| 想用 reference_audio 驱动口型被 400 | reference_audio 属多模态参考模式，和 first_frame 互斥；2.0 还不能只传音频 | 硬首帧只靠引号台词唇同步，不为口型丢首帧。高棉语等不支持的语种后期配 |
| 长提示词后半段不执行、细节丢 | 中文建议 ≤500 字，超长丢细节，不报 400 | 编包 500 字软闸：先砍装饰词和重复外观，保身份 / 站位 / 起点状态 / 视线 / 手 / 道具 / 时序 / 光 |
| 写了「不要 X」反而出 X | 否定句被忽略或反做 | 只写肯定句；禁止项过 ban_dictionary 翻成正向替代（暗 → 低调光一盏钨丝灯；不要抖 → 机身锁死） |

## 能力

核对日 2026-09-09，与 `seedance_2_5.md` 同一账号。QC 回写会丢掉本节，以 2.5 页和 `## 种子` 为准。

- 本账号可见：`doubao-seedance-2-0-260128`（480p–4k）、`doubao-seedance-2-0-fast-260128` 与 `doubao-seedance-2-0-mini-260615`（仅 480p/720p）。无视频 Endpoint。
- `duration` 4–15 或 -1，默认 5。`ratio` 可显式 `16:9`。`generate_audio` 默认 true。无 `camera_fixed` / `frames` / `omni_reference_task_type` / `output_format`。
- 语音：`generate_audio=true` 时台词放引号 + 语种 + 语气即唇同步；原生中 / 英 / 日 / 韩 / 西 / 法 / 德，无高棉语。本剧中文工作轨 `speech_mode=seedance_native`，台词只在 `audio_block`；高棉语 Gate F。`reference_audio` 与 `first_frame` 互斥，不用。
- 与 2.5 的编包差：2.5 时长上限 30、参考图上限 30、首帧任务必须 `ratio=adaptive`、多一个 `omni_reference_task_type`。互斥规则相同。本集 confirm 锁 2.0，包按 4–15 编即可复用。
