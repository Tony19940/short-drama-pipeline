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

## 能力

核对日 2026-09-09，与 `seedance_2_5.md` 同一账号。QC 回写会丢掉本节，以 2.5 页和 `## 种子` 为准。

- 本账号可见：`doubao-seedance-2-0-260128`（480p–4k）、`doubao-seedance-2-0-fast-260128` 与 `doubao-seedance-2-0-mini-260615`（仅 480p/720p）。无视频 Endpoint。
- `duration` 4–15 或 -1，默认 5。`ratio` 可显式 `16:9`。`generate_audio` 默认 true。无 `camera_fixed` / `frames` / `omni_reference_task_type` / `output_format`。
- 与 2.5 的编包差：2.5 时长上限 30、参考图上限 30、首帧任务必须 `ratio=adaptive`、多一个 `omni_reference_task_type`。互斥规则相同。本集 confirm 锁 2.0，包按 4–15 编即可复用。
