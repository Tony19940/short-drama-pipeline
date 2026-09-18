# 导演层 · 场合同拆镜

拆镜 Agent 是导演层的发动机。它不写故事、不出视频。它只决定这场戏拍哪些镜头。5.1 说明书和 5.2 生成包是后面两岗，不要写进这一岗。
人先审整场，再锁单镜。提示词是合同的译文，不是另写的作文。

对照：Toonflow / LocalMiniDrama 的画布当视图；Jellyfish 的镜头准备态；
shuohao 的「分镜只输出」和 2-5 秒对白门；BigBanana 的首尾帧（其 Seedance 路线实际丢尾帧，首尾帧只在 veo/vidu 成立）；drama-skills 的人确认后才投产。

## 留下

- 真源仍是 productions/<slug>/
- 人锁关卡；草稿先于正式表
- 舞台 / blocking.jpg / 第 0 秒 start
- 从父图改，不准另开新脸
- 对白不进 video_prompt
- H3 三字段、出片指纹、Ken Burns 禁令

## 扔掉

- 覆盖表一行自动变一镜、机位轮换、默认全 static
- 只审单镜、提示词可抄上一镜
- 换机位就当新海报
- 把 concat 全长拼接当成导演完成

## 拆镜依据

1. 已锁的本、场次、舞台、主图。不许再编情节。
2. knowledge/director/playbook.md：永远生效的短打法。
3. knowledge/cases/：拉片蒸馏的场型卡，一场只用最像的一两张。
4. 写字模型只填句。刀法不来自模型记忆。

## 一场合同

每场先定轴和 2-3 个机位（另加 insert）。镜头必须挂 rig_id。
对白镜跟台词走；邻镜写成动作对；video_prompt 必须含本镜 action。
续镜第 0 秒 start 必须已经在动作中间，不能站好再开始。
对白/心里台词后插 1.2–2.0 秒无台词反应镜。
每镜合同带 handle=2 / render_seconds=seconds+2，给以后的 EDL 留修剪余地；assemble.sh 这期仍全长拼接。纸面目标 14–18 镜/分；要上 16–18 必须按纸面秒裁。
写字模型只填句。没有密钥时启发式填 start/action/landing，禁止按剧情关键词写死英文。

## 电影级拆镜（shot-table-v2）

导演 Agent 不再一上来就拆。顺序固定：

```
阐述 → 表头 → 每场 N 版 → 评审 → 人选 → 画面描述 → animatic
```

1. **阐述**（`analysis`，一次）：每场一张场卡——戏剧问题、翻转点（逐字引剧本）、情绪曲线 0–10、那一颗（瞬间 + 景别）、揭示顺序、距离策略、光的动机、静音测试；全集一份视觉语法（母题、景别节奏、结尾钩子景别）。落 `.pipeline/scene_cards.json`、`03-storyboard/scene-cards.draft.md`。
2. **表头**（`header`）：视点、每场左右锁、连戏圣经、每场镜数秒数节拍。已经看见卡。
3. **每场 N 版**（`scene` × N，默认 3）：覆盖派 / 主观派 / 少切派各拆一版，各自过机器校验，不过带错误清单重来一次。风格不许破卡。
4. **评审**（`critic`）：七维打分（揭示顺序、那一颗、节奏、静音、卡的承接、连戏、模型风险），挑一版，写为什么、写合并建议。评审不可用就机器兜底。
5. **人选**：`03-storyboard/shot-candidates.draft.md` 并排看；导演台「选这版」换版不花 token。正式表只收被选的那版。
6. **画面描述**（`frame_desc`，一场一次）：每镜一段能画的画——三层、光位、手、构图重心、机高意味、不得出现。关键帧岗照这段画，生成包 `image_prompt` 带它。
7. **animatic**：`scripts/animatic.py` 把锁定首帧按秒数切成审片片，看节奏。不是成片路径。

**一镜一机位。** 默认不片内切。换机位、换景别合同、切反应，都开新镜。`in_from` / `out_to` 只写本机位起幅和落幅，不写「立刻切下一镜」。能力档 `max_internal_cuts=0`；要开片内切是未来某剧的 opt-in，不是本仓库默认。

机器在拆镜时多查这些（`director/direction.py`）：

- 那一颗：卡说的景别必须有自己的一镜，且是全场最紧（没有 = error；不是最紧 = warning）。
- 母题：`first_shot_in_scene` / `first_appearance` / `always` 三种时机，`scale_not` / `scale_in` / `angle` 违反 = error。
- 节奏：三镜连着同景别、四镜以上景别不跨档、峰值镜不够紧、峰值后不回中景 = warning。SPM < 12、连续两镜 ≥8s、对白后无反应 = warning（新纸面表 SPM / 无理由 >8s / 复合动词 = error；已锁成片只 warning）。
- 光位：同场主光一个方向，反打可以镜像；left↔right 直跳 = error；`day_night` 和 bible 不符 = error。
- 邻镜差：景别 / 角度 / 左右 / 运镜 / 主体最多改两件，改三件 = warning。
- 机位：`camera_id` 不在 `sets.cameras[]` = error；设计的左右和顶视图几何不一致 = warning（`director/camera_plot.py`）。
- 模型经验：QC 回写的 `knowledge/model-notes/<model>.md` 前 12 条进 `target_profile.experience`，拆镜和评审都看得见。

旧的 `shots.json` 路径仍在（下表），Gate C 的 `check_prod.py` 不变。新剧走 `.pipeline/shot_list.json`。

## 文件

| 文件 | 谁写 |
|---|---|
| knowledge/director/playbook.md | 手册（含场卡 / 那一颗 / 光位 / 邻镜差） |
| knowledge/cases/*.md | 场型卡，格式见 `knowledge/cases/README.md` |
| .pipeline/scene_cards.json | 场戏分析 Agent：场卡 + 视觉语法 |
| .pipeline/design.candidates.json | 每场 N 版 + 评审 + 选版 |
| .pipeline/shot_list.json | 被选版合成的正式镜头表（shot-table-v2） |
| .pipeline/frame_descriptions.json | 画面描述 Agent：每镜第二描述层 |
| .pipeline/model_feedback.json | QC 回写；同时重写 knowledge/model-notes/<model>.md |
| 03-storyboard/scene-cards.draft.md · shot-candidates.draft.md · shot-list.draft.md · frame-descriptions.draft.md | 人审页，机器渲染 |
| 03-storyboard/animatic/epNN.animatic.mp4 | 静帧 animatic，只给审 |
| 02-assets/scenes/<id>/camera-plot.png | 机位顶视图 |
| 03-storyboard/shots.draft.json | 旧路径拆镜草稿，带 directing / scenes / shots |
| 03-storyboard/shots.json | 旧路径人接受后的正式表 |

Gate C 对 directing=scene-rig-v1 的新表执行硬检查；旧正式表只警告，不挡 003/004/005 回归。
005 已锁成片和正式分镜先不动。新草稿走新刀法。

