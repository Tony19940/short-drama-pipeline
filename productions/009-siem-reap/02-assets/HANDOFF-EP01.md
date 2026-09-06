# 第 1 集 Gate B 出图交接

把下面「给接手当 Agent 的第一段」整段贴给另一个 agent。本文件是任务书。锁定卡已经写在各 `.md` 里，不要再发明外貌。

---

## 给接手当 Agent 的第一段（可复制）

你只做《暹粒》第 1 集 **Gate B 视觉资产**。项目：`productions/009-siem-reap`。成片模型是 Seedance 2.0，但你不出视频、不出关键帧、不写分镜。

先读：

1. `productions/009-siem-reap/02-assets/HANDOFF-EP01.md`（本任务书）
2. `productions/009-siem-reap/02-assets/LOOK.md`
3. 仓库根目录 `AGENTS.md`
4. 各角色/场景/道具卡（路径见下方清单）

然后按本文件的顺序生图，用 `scripts/place_codex_asset.py` 落到正式 jpg。做完只更新 `02-assets/` 和必要时 `.pipeline/assets.json`。不要写 `03-storyboard/shots.json`，不要改锁定分镜。

---

## 这岗是什么

资产 = 这个人 / 这处空间 / 这件道具 **长什么样**。护照图、空镜、静物。

不是：某一镜的构图、站位、对白、坠落、绑绳、陷泥、火把一行行灭。那些是 6.1 关键帧。

第 1 集分镜已锁：`03-storyboard/shot-list.md`（21 镜 / 136 秒）。你只许从里面抄 **服装、日夜、道具存亡**，不许按某一镜出图。

## 出图前还要不要准备

锁定卡、LOOK、清单、落盘脚本已经齐。接手前确认：

- [x] 分镜已锁，不用等 19 镜稿
- [x] 角色/场景/道具卡已补锁定卡（剧本没写的字段是空的，禁止补完）
- [x] 两个「或」已生产锁定：速卡发型 = **低马尾短黑发**；守卫 = **干燥布甲夜岗**（与云朗简甲区分）
- [x] LOOK 含色板、反塑料脸、文化禁止项
- [ ] 磁盘上还没有一张正式 `master.jpg`（这是你的工作）
- [ ] **不要**先写 `.pipeline/assets.json`（没图就没有 file）
- [ ] **不要**做 blocking.jpg、生成包、关键帧
- [ ] 帕东 / 萨里 / 沙蒙 / old-sluice / dry-bed / elephant-camp / water-gate：**本轮不出图**，也不要给它们建带 jpg 的文件夹（导演台 Gate B 会扫所有角色/场景子目录，空目录或缺图会卡住）

可选、建议先做一张：**ancient-shoal 黄昏空镜当 look-test**。色板不对就停，不要往下画人。

`sheet.jpg` / 正侧背不是本轮硬门槛；Gate B 最低是每人 `master.jpg` + `face.jpg`，每场空镜 `master.jpg`。要做 sheet，必须从已有 master 改，禁止 `sheet-candidate-*` 自动晋升。双人 `scale.jpg` 本轮可跳过（圣经没有身高数字）。

## 硬规则

1. `master` 只许全新生成一次。`face` / 湿衣 / 断槽 / 夜芦苇岸 必须对着父图 edit，禁止另开新脸、新槽、新河。
2. 已有正式 jpg 不要直接覆盖，走 `place_codex_asset.py`（它会把旧文件留成 `master-v1.jpg`）。
3. 人物提示词末尾加 LOOK 里的 anti_plastic。这段不写进身份锁定卡。
4. `inferred_empty` 的字段：提示词不写，图里不画（不要编雀斑、义肢、精确身高、瞳色）。
5. 空镜不要人。道具静物不要手演戏。
6. 不要导演台 Imagine / inbox。Codex 用内置 imagegen；Cursor 用自带生图。生成文件再用脚本落盘。
7. 不要写 `03-storyboard/shots.json`。不要改 `shot-list.md` / `.pipeline/shot_list.json`。

## 落盘

```bash
python3 scripts/place_codex_asset.py \
  --prod productions/009-siem-reap \
  --kind character \
  --slug sokha \
  --slot master \
  --src "$CODEX_HOME/generated_images/那张图.png"
```

`kind`：`character` | `scene` | `prop`  
`slot`：人物 `master` `face` `front` `side` `back` `sheet`；场景 `master`；道具只有 `master`。

湿衣用 `--kind character --slug sokha-wet --slot master`。  
夜芦苇岸用 `--kind scene --slug ancient-shoal-night --slot master`。

## 顺序（不要打乱）

父图没落地，不准画子图。

1. （建议）`scenes/ancient-shoal/master.jpg` 黄昏空镜，当 look-test
2. `characters/sokha/master.jpg` → `face.jpg`
3. `characters/sokha-wet/master.jpg`（edit sokha master；可再出一张 wet face，仍是同一张脸）
4. `characters/yunlong/master.jpg` → `face.jpg`
5. `characters/patrol/master.jpg` → `face.jpg`（甲跟云朗，脸必须是另一个更年轻无须的人）
6. `characters/guard/master.jpg` → `face.jpg`（布甲，不是云朗）
7. `characters/siamese-rider/master.jpg` → `face.jpg`
8. `scenes/modern-channel/master.jpg`（空镜，槽完整；不要测量杆、不要人）
9. `scenes/granary/master.jpg`（夜空镜，不要人）
10. `scenes/ancient-shoal-night/master.jpg`（从 dusk 浅滩改夜芦苇，远处可有寨火和粮垛尖顶，不要人）
11. `props/survey-pole/master.jpg`
12. `props/sluice-intact/master.jpg`（与 modern-channel 里那块槽同一形状）
13. `props/sluice-broken/master.jpg`（**edit 完整槽**）
14. `props/hemp-rope/master.jpg`
15. `props/grass-snare/master.jpg`（看起来不是麻绳）

若时间不够：先保证 **sokha 干+湿、yunlong、三场空镜、完整槽+断槽**。巡丁/游骑/守卫/绳/杆可以第二批，但缺它们第 1 集没法进 5.2。

## 文件清单

| 正式路径 | 父图 | 读哪张卡 |
|---|---|---|
| `02-assets/characters/sokha/master.jpg` | 无（全新） | `characters/sokha.md` |
| `02-assets/characters/sokha/face.jpg` | sokha/master | 同上 |
| `02-assets/characters/sokha-wet/master.jpg` | sokha/master | `characters/sokha-wet.md` |
| `02-assets/characters/yunlong/master.jpg` | 无 | `characters/yunlong.md` |
| `02-assets/characters/yunlong/face.jpg` | yunlong/master | 同上 |
| `02-assets/characters/patrol/master.jpg` | 无（甲参考云朗） | `characters/patrol.md` |
| `02-assets/characters/patrol/face.jpg` | patrol/master | 同上 |
| `02-assets/characters/guard/master.jpg` | 无 | `characters/guard.md` |
| `02-assets/characters/guard/face.jpg` | guard/master | 同上 |
| `02-assets/characters/siamese-rider/master.jpg` | 无 | `characters/siamese-rider.md` |
| `02-assets/characters/siamese-rider/face.jpg` | siamese-rider/master | 同上 |
| `02-assets/scenes/modern-channel/master.jpg` | 无 | `scenes/modern-channel.md` |
| `02-assets/scenes/ancient-shoal/master.jpg` | 无 | `scenes/ancient-shoal.md` |
| `02-assets/scenes/ancient-shoal-night/master.jpg` | ancient-shoal/master | `scenes/ancient-shoal-night.md` |
| `02-assets/scenes/granary/master.jpg` | 无 | `scenes/granary.md` |
| `02-assets/props/survey-pole/master.jpg` | 无 | `props/survey-pole.md` |
| `02-assets/props/sluice-intact/master.jpg` | 无 | `props/sluice-intact.md` |
| `02-assets/props/sluice-broken/master.jpg` | sluice-intact/master | `props/sluice-broken.md` |
| `02-assets/props/hemp-rope/master.jpg` | 无 | `props/hemp-rope.md` |
| `02-assets/props/grass-snare/master.jpg` | 无 | `props/grass-snare.md` |

## 连戏（只用于别画错，不要画成戏）

- 速卡全剧现代勘测服，不换古装。开场干，落水后湿透沾泥。
- 测量杆只存在现代场；古岸空手。
- 石槽：现代完整可伸指 → 古岸同一槽口断残。
- 麻绳只在古浅滩；粮栈换草绳套。
- 云朗岸上基本是干的。守卫干燥。
- 浅滩黄昏；芦苇岸夜；粮栈夜；现代场暴雨白天。

## 完成后你要做

1. 用 `place_codex_asset.py` 确认上表路径都在。
2. 写 `.pipeline/assets.json`：每条含 `asset_id, type, name, binds_to, file, what_it_locks, version, lock_card, image_prompt`；人物/服装加 `quality_layer`（anti_plastic 原文）。`asset_id` 用各卡上已写的 ID。
3. 在 `01-bible/STATUS.md` 把资产从「未出图」改成「Ep01 Gate B 图已落盘，待人眼过」。
4. **停。** 不要跑 5.2，不要出关键帧。人眼过图之后才进入生成包。

交还时列：每张正式路径、父图是哪张、有没有另开新脸/新槽、LOOK 禁止项有没有误画（国旗、城市、字幕、日甲、旗袍）。
