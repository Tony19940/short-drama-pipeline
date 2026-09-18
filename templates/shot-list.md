# 分镜表 · 第 __ 集

- **状态**：draft | review | locked
- **画幅**：16:9
- **总镜数**：
- **总时长**：跟分镜走，等于各镜秒数之和
- **声音**：每镜一种：口述 / 心里 / 旁白 / 出场简介 / 短信

先写 `01-bible/blueprint.md` 和 `beats.md`。开场先让人站住，第一场里冲突必须发生。`shots.json` 必填 `new_info` / `from` / `cut` / `scale` / `scene` / `facing` / `expression` / `blocking`。跑 `scripts/check_storyboard.py`。

纸面秒按桶：反应 1.2–2.0 · 插入 1.5–2.5 · 对白 2.5–4.5 · 建立 3–5 · 长镜 5–8。目标 14–18 镜/分。不要为模型 4s 底把反应垫长。

| 镜号 | 秒 | 档 | 景别 | 切 | 朝向 | 新信息 | @角色 | @场景 |
|---|---|---|---|---|---|---|---|---|
| SH001 | 4 | fast | med | 开场 | 低头 | | | |

## 声音对照

| 镜号 | 种类 | 说话人 | 工作轨 |
|---|---|---|---|
| SH001 | intro | | |

## 单镜写法

每镜另起一节，提示词保持短、现在时、单一运动。

### SH001

- **节拍**：
- **首帧**：谁在哪，什么姿态，光从哪来
- **运动**：
- **声音**：口述 / 心里 / 旁白 / 出场简介 / 短信
- **视频提示词**：

每镜必填导演字段：`lens` / `axis` / `camera` / `action` / `look` / `video_prompt` / `negatives`。
`video_prompt` 写给视频模型：画幅、焦段、景别、一次运镜、一件动作、光线站位、禁止项。对白不准写进去。

合法运镜见 [camera-moves.md](camera-moves.md)。提示词公式见 [video-prompt-formula.md](video-prompt-formula.md)。角色联络板见 [character-sheet-prompt.md](character-sheet-prompt.md)。
