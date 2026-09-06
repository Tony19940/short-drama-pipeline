# 第 1 集 6.1 首帧交接（Codex）

把下面「给接手当 Agent 的第一段」整段贴给 Codex。本文件是任务书。

---

## 给接手当 Agent 的第一段（可复制）

你只做《暹粒》第 1 集 **6.1 关键帧静帧**。项目：`productions/009-siem-reap`。成片模型是 Seedance 2.0，但你**不出视频**、不改分镜、不写 `03-storyboard/shots.json`。

先读：

1. `productions/009-siem-reap/03-storyboard/HANDOFF-FRAMES-EP01.md`（本任务书）
2. `productions/009-siem-reap/.pipeline/gen_packages.json`（已 `confirmed=true`；用每镜的 `image_prompt`、`asset_refs`、`continuity`、`keyframe_plan`）
3. `productions/009-siem-reap/03-storyboard/sets.json`（左右轴）
4. `productions/009-siem-reap/02-assets/LOOK.md`
5. 仓库根目录 `AGENTS.md`

出图必须 **edit 父图**，禁止文生图另开新脸。落盘用 `scripts/place_codex_frame.py`。画幅 **16:9**，不要 9:16。

---

## 这岗是什么

关键帧 = **这一镜第 0 秒的构图**：谁站哪、看哪、景别、起幅姿势。

不是护照、不是空镜、不是道具静物。那些已经在 `02-assets/`，只许当参考。

`keyframe_plan=first`：只出 `04-frames/SH0xx.jpg`。  
`keyframe_plan=first_last`：先出首帧，再从首帧改尾帧 `04-frames/SH0xx-last.jpg`，只改分镜要求改变的那一件事。

## 出图前还要不要准备

已经齐：

- [x] Gate B 资产 21 张正式 jpg
- [x] 生成包 21 条，`confirmed=true`，`episode_target_model=seedance_2_0`
- [x] 镜头表 / 说明书已锁
- [x] 落盘脚本 `scripts/place_codex_frame.py`

不要做：

- [ ] **不要**写 `03-storyboard/shots.json`
- [ ] **不要**出 `blocking.jpg`（本集用空镜 + `sets.json` 轴线，不走旧舞台打点）
- [ ] **不要**补正侧背 / sheet（可选身份参考，不是本岗门槛）
- [ ] **不要**改粮栈空镜去画水线；水线是 **SH019** 的构图，在首帧里加
- [ ] **不要**调用视频模型
- [ ] **不要**自己把 `keyframes.json` 标成 qc pass（落盘后等人眼过）

## 硬规则

1. 画幅 16:9。知识库 6.1 默认 9:16 **不适用于本集**。
2. 父图链：一场的第一镜从该场空镜 `master.jpg` 改；同场后续镜从**上一镜已落盘的首帧**改；尾帧从**本镜首帧**改。禁止对着空气文生一张新速卡。
3. 先 `view_image` 父图和 `asset_refs` 对应文件，再 edit。
4. 站位、视线必须对 `continuity` 和 `sets.json` 轴线。SC01：槽与人偏左，河在画右。SC02：高棉岸画左，暹罗对岸画右。SC03：柱在画左，守卫从画右入。
5. 人物提示词末尾加 LOOK 的 anti_plastic。近景/特写尤其要。
6. 已有正式 jpg 不要直接覆盖，走落盘脚本。
7. 不要导演台 Imagine / inbox。

## 落盘

```bash
python3 scripts/place_codex_frame.py \
  --prod productions/009-siem-reap \
  --shot SH001 \
  --slot first \
  --src "$CODEX_HOME/generated_images/那张图.png"
```

尾帧把 `--slot first` 换成 `--slot last`。

## 父图链

| 镜 | 场 | 首帧父图 | 计划 | 备注 |
|---|---|---|---|---|
| SH001 | 暴雨河道 | `scenes/modern-channel/master.jpg` | first_last | 本场地理锁。先做这一张 |
| SH002 | 同上 | `04-frames/SH001.jpg` | first | 手指伸进完整凹痕 |
| SH003 | 同上 | `04-frames/SH001.jpg` | first_last | 干衣，看河 |
| SH004 | 同上 | `04-frames/SH003.jpg` | first_last | **最难**。尾帧：人杆没入画右，槽空着 |
| SH005 | 黄昏浅滩 | `scenes/ancient-shoal/master.jpg` | first_last | 湿衣，无杆 |
| SH006–SH015 | 同上 | 上一镜 `04-frames/SHxxx.jpg` | 见生成包 | SH013 **最难**（陷泥），SH015 只出首帧 |
| SH016 | 夜芦苇岸 | `scenes/ancient-shoal-night/master.jpg` | first_last | 换空镜，仍湿衣无绳 |
| SH017 | 粮栈 | `scenes/granary/master.jpg` | first_last | 草绳套，尚未进门也可以 |
| SH018 | 同上 | `04-frames/SH017.jpg` | first_last | 绑上画左柱 |
| SH019 | 同上 | `scenes/granary/master.jpg` | first | **最难**。只拍柱脚水线，空镜里没有水线，本镜加上 |
| SH020 | 同上 | `04-frames/SH018.jpg` | first | 近景反应 |
| SH021 | 同上 | `04-frames/SH018.jpg` | first_last | 尾帧切到她低声说「水要来了」 |

参考图按该镜 `asset_refs` 去 `assets.json` 的 `file`。不要把护照 `master.jpg` / `face.jpg` 直接另存成首帧。

## 顺序

不要跳着从 SH004 开画。同场左右轴还没锁住，坠落会漂。

1. SH001 首帧（本集 look-test：暴雨河道 + 人槽左右）
2. SH002 → SH003 → SH004 首帧 → SH004 尾帧
3. SH005 起做浅滩整条，SH013 在条里做，不要单独另开一张河
4. SH016 换夜空镜
5. SH017–SH021；SH019 可在进栈后单独做水线特写

若只想先验证 6.1 能不能从空镜改构图：做 **SH001 首帧**，色板/左右不对就停。

## 做完交什么

- `productions/009-siem-reap/04-frames/SH0xx.jpg`（21 张首帧）
- `first_last` 的 `SH0xx-last.jpg`（15 张：SH001, SH003, SH004, SH005–SH010, SH012, SH014, SH016–SH018, SH021）
- 不要写 `shots.json`，不要改 `shot-list.json`，不要标生成包 `keyframe_files`

人眼过图后再写 `.pipeline/keyframes.json`。
