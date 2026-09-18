# 流水线规则（模仿小云雀）

对照：小说 → 编剧 → 资产 → 分镜设计 → 说明书(5.1) → 生成包(5.2) → 关键帧 → 视频 → 声音 → 剪辑。交接 JSON 在 `.pipeline/`。  
细则 `XIAOYUNQUE.md`。分镜不是海报表。导演台 8 个 Agent 对应这些关；文件真相仍在 `productions/`。

任何一关说「改」，只重做该关及下游。上游正式文件指纹变了，下游标 stale，禁止未重审出片。已锁定的主图不换，除非你明确要求换脸或换画风。

一百集合集的总簿在 `productions/khmer-stories/`。单集仍走本文件。神话旁白集可空镜，但一样要标场。

反推参考片仍藏在 `00-reverse/`，不进 8 Agent 轨。不要和故事 Gate 0（`01-bible/source/`）撞车。

## 关卡

```
参考成片（可选，隐藏）
        │
        ▼
 [Gate 0]  故事：启动 InkOS 写小说后导出上传 / 本地小说或剧本 → 01-bible/source/
        │
        ▼
 [Gate A]  编剧：剧本 + 确认 + 蓝图
        │
        ▼
 [Gate P]  制片：缺口清单 + 任务单（不生图）
        │
        ▼
 [Gate B]  美术：角色/场景主图
        │
        ▼
 [Gate S]  舞台（内部；人锁导演时一起过）
        │
        ▼
 [Gate C]  导演：覆盖 + 分镜合同
        │
        ▼
 [Gate D/E]  摄影出片：首帧 + 单镜视频
        │
        ▼
 [Gate E+] 声音：音效床 + 审剧情轨 + 声音合同
        │
        ▼
 [Gate F]  审片：报告 + 成片
```

| 关 | 目录 | 通过标准 |
|---|---|---|
| 0 | `01-bible/source/` | `source.json`、`original.md`、大纲/人物/时间线。旧项目没有 `source/` 时从 CAST/blueprint/ep01 **只读合成**，不改写正式剧本 |
| 反推 | `00-reverse/` | 参考 mp4、切点、关键帧、转写。隐藏路径，不锁定、不出片 |
| A | `01-bible/` | `ep01.md`、`confirm.md`、`blueprint.md`；勾完 `CULTURE.md` |
| P | `01-bible/producer/` | `plan.md` + `manifest.json`。只列缺 master/face/sheet 的任务 |
| B | `02-assets/` | 角色 master+face；双人有身高图；场景空镜 master（3/4 机位、一个锚点物、一套光逻辑）。锁 master 前 10 张压力测试 ≥9/10；每角色一句 `descriptor`（不写年龄），有台词的带 `voice_card`；`sets.json` 每场 `geo_zh` |
| S | `03-storyboard/sets.json` + `blocking.jpg` | 每场有人站哪；内部检查，人锁导演 Agent |
| C | `03-storyboard/` | `coverage.md` `beats.md` `shots.json`。`check_prod.py` 必须过 |
| D/E | `04-frames/` `05-shots/` | 设计首帧 FL2VA；同机位续才吃 `{from}-last.jpg`；设计尾帧走 `end_frame`；Ref2VA 未安装就停 |
| E+ | `07-dubbing/sfx/` `06-export/preview-*-vo.mp4` `07-dubbing/` | 先 `mix_episode_sfx.py` 按 `key_sfx` 混音效床，再 `mix_review_track.py` + 声音合同。中文对白是 Seedance 原声（`speech_mode=seedance_native`），声音岗只清理对齐，原声缺 / H3 镜才重录。无声切不能当审剧情 |
| F | `06-export/ep01.mp4` `08-qc/` | 审片报告。脚本判过关；无视觉模型时 `inconclusive`。高棉语配音 / 字幕在这一关（`DUBBING.md`） |

未通过不进入下一关。Agent 只写 `*.draft.*`，人点「接受并锁定」才进正式文件。Gate A 讨论期间不生图。  
硬规则 **R1–R14** 见 `QUALITY.md`。文化词典见 `CULTURE.md`。出片路由见 `VIDEO.md`。  
Gate D/E 手工走 Grok Imagine 画布见 `GROK-CANVAS.md`。

入口：

```bash
python3 scripts/reverse_video.py --prod productions/<slug> --video /path/to/ref.mp4 --localize --no-grok
python3 scripts/check_prod.py --prod productions/<slug>
python3 scripts/render_blocking.py --prod productions/<slug>
python3 scripts/render_camera_plot.py --prod productions/<slug> [--check]
python3 scripts/animatic.py --prod productions/<slug> [--episode 1] [--audio 07-dubbing/xxx.m4a] [--fps 24] [--plan]
python3 scripts/render_shots.py --prod productions/<slug> --only SH001 --review-track
python3 scripts/mix_episode_sfx.py --prod productions/<slug> --dry-run
```

`render_camera_plot.py` 读 `sets.json` 的 `marks[]` + `cameras[]`，画 `02-assets/scenes/<id>/camera-plot.png`，`--check` 只报轴线（180° 规则、每机位左→右顺序）。  
`animatic.py` 把 `04-frames/` 已锁首帧按镜头表秒数切成 `03-storyboard/animatic/epNN.animatic.mp4`，缺首帧是灰卡。**审片工具，不是成片路径**：和 Ken Burns 一样进不了 `05-shots/`、`06-export/`（`assemble.sh` 拒收 `*animatic*`，见 `VIDEO.md`）。

## 命名

```
角色主图      02-assets/characters/<slug>/master.jpg
场景空镜      02-assets/scenes/<slug>/master.jpg
舞台机位      02-assets/scenes/<slug>/blocking.jpg
机位顶视图    02-assets/scenes/<slug>/camera-plot.png
分镜合同      03-storyboard/shots.json（旧路径）／ .pipeline/shot_list.json（shot-table-v2）
场卡草稿      03-storyboard/scene-cards.draft.md · shot-candidates.draft.md · frame-descriptions.draft.md
静帧 animatic 03-storyboard/animatic/ep01.animatic.mp4（只给审）
场次舞台      03-storyboard/sets.json（marks[] + cameras[]）
首帧          04-frames/SH001.jpg
上一镜末帧    04-frames/SH001-last.jpg
单镜视频      05-shots/SH001.mp4
审剧情        06-export/preview-30s-vo.mp4
音效床        07-dubbing/sfx/ep01-sfx.m4a
成片          06-export/ep01.mp4
```

## 生成规则

### 图片

1. 每个角色、每个主场景只允许一次全新生成，得到 `master`。
2. 换装、把人塞进场景、下一镜差分，全部从上一张改。
3. **一场的第一张有人的图从该场 `blocking.jpg`（或空镜 master + 角色卡）改，禁止对同一场另开一张摆拍。**
4. 角色卡写 Markdown。需要字的卡面用 HTML/CSS。
5. 邻镜只改一件事。机位、天色、衣服、人数保持住。换场先写硬切。

### 分镜（导演层）

0. 走 shot-table-v2 的剧先出场卡：导演 Agent 先 `analysis`（每场戏剧问题 / 翻转点 / 那一颗 / 揭示顺序 / 光的动机），再表头，再每场 N 版，评审挑一版，人可改选，再写画面描述。草稿在 `03-storyboard/scene-cards.draft.md`、`shot-candidates.draft.md`、`shot-list.draft.md`、`frame-descriptions.draft.md`；机器多查那一颗、母题、节奏、同场光位、邻镜差。细则 `DIRECTOR.md`。
1. 先写 `sets.json` 和 `coverage.md`。默认画幅 **16:9 横幅**。镜数和单集时长跟分镜走，等于各镜秒数之和，不设 50–75 秒上限，也不为凑时长注水。
2. 单镜秒数按这一镜的动作和台词定，走纸面桶（反应 1.2–2.0，对白 2.5–4.5，长镜 5–8）。覆盖需要时 close 可以短于 master，不要为均分而 6+6+6。目标 14–18 镜/分。
3. 每镜只推进一件新信息。同场同人同景别同朝向禁止连排。
4. `setup` 必须是 `master` / `close` / `ots` / `insert` / `single`。一场里不能全是 `single`。
5. 同场 `cut=continue`。硬切只换场。
6. `python3 scripts/check_prod.py` 不过关不准出视频。

### 视频

1. 先有你审过的首帧，再生成该镜。
2. 提示词：一个主体 + 一个运动。`move` 与提示词里的运镜必须一致。
3. **主路径永远是锁定首帧 FL2VA。** `cut=continue` 且同机位、人物有交集、存在 `{from}-last.jpg` 时，才把上一镜真末帧当这一镜的第 0 秒。换机位或切人仍用本镜设计首帧。
4. **设计尾帧可选。** `end_frame` 指向一张人审过的静帧（`04-frames/SHxxx-end.jpg`）。生成后抽出的 `{id}-last.jpg` 只给下一镜同场续用，不能回填成这一镜的尾帧。
5. **防换脸靠参考外挂。** `sheet.jpg` / `face.jpg` 走 Ref2VA 节点，挂在首帧外面，采样仍走 FL2VA。不许用参考图替代第 0 秒。
6. ffmpeg concat 同分辨率同帧率。
7. 中文对白走 Seedance 原声唇同步：台词只在 `audio_block`（声线卡逐字 → 引号台词 + 语种 + 语气 → 只说这一句 → 不说话的人嘴闭着 → 环境声、无音乐、无字幕）；说话时的动作和表情在紧跟的【表演】句里。有词镜 `dialogue_delivery=on_camera`；写 `post` 的镜退成 `post_dub`（不出原声）。H3 / Hailuo 路线没有原声，对白后期叠。角色参考图仍校验存在；CompShare 提交时丢掉参考图。
8. 首帧 = 动作起点状态（可已起手，禁结果）；motion 从 0.0s 就在动，只写肯定句，段首粘本场 `geo_layout`。
8. 默认 Hailuo Fast 无声；`tier=h3` 每集不超过 3 镜。

### 旁白与声音

1. 都市短剧：C2 就写 `line` / `caption` / `line_kind` / `speaker`。种类是口述、心里、旁白、出场简介、短信。出完画面立刻 `mix_review_track.py`。
2. 神话集：整段一次 TTS，画面跟人声气口走。见 `productions/khmer-stories/SOUND.md`。
3. 成片高棉语是 Gate F，中文工作轨是 Gate E+。两套都要，不能用工作轨冒充成片。中文工作轨对白由 Seedance 原声唇同步（`speech_mode=seedance_native`），声音岗只降噪、统一音色、放进空间；Seedance 没有高棉语，高棉语只能配音 / 字幕。
4. 都市短剧：先 `scripts/mix_episode_sfx.py` 混音效床，再 `scripts/dub_silent_episode.py` 贴高棉语对白。见 `DUBBING.md`。
5. **R12** BGM 高棉流行或婚礼锣鼓。H3 人声不当配音。Seedance 原声对白核对等于原句后是中文工作轨成品声；即兴碎话、自带音乐不进成片，环境床仍只落实锁定表 `key_sfx[]`。
6. **R1–R2** 人名不译。


## 导演台入口

本机 UI 把上述关卡做成可点的锁定轨，源文件仍是本目录结构。启动：`bash scripts/run_director.sh`。详见 `STUDIO.md`。


脚本专家（导演台剧本页）只写 `*.draft.*`。优先把已有 `coverage.md` 编译成 6–10 镜合同，运镜句来自 `templates/camera-moves.md`，不另造一套 MJ/SD 提示词。正式分镜仍要人审 + `check_prod.py`。

导演层细则见 `DIRECTOR.md`。拆镜 Agent 按场合同出草稿：2–3 个机位、对白镜短、提示词含本镜动作。覆盖表是证据，不是一行一镜。
