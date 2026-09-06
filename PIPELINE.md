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
 [Gate E+] 剪辑声音：审剧情轨 + 声音合同
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
| B | `02-assets/` | 角色 master+face；双人有身高图；场景空镜 master |
| S | `03-storyboard/sets.json` + `blocking.jpg` | 每场有人站哪；内部检查，人锁导演 Agent |
| C | `03-storyboard/` | `coverage.md` `beats.md` `shots.json`。`check_prod.py` 必须过 |
| D/E | `04-frames/` `05-shots/` | 设计首帧 FL2VA；同机位续才吃 `{from}-last.jpg`；设计尾帧走 `end_frame`；Ref2VA 未安装就停 |
| E+ | `06-export/preview-*-vo.mp4` `07-dubbing/` | `mix_review_track.py` + 声音合同。无声切不能当审剧情 |
| F | `06-export/ep01.mp4` `08-qc/` | 审片报告。脚本判过关；无视觉模型时 `inconclusive` |

未通过不进入下一关。Agent 只写 `*.draft.*`，人点「接受并锁定」才进正式文件。Gate A 讨论期间不生图。  
硬规则 **R1–R12** 见 `QUALITY.md`。文化词典见 `CULTURE.md`。出片路由见 `VIDEO.md`。  
Gate D/E 手工走 Grok Imagine 画布见 `GROK-CANVAS.md`。

入口：

```bash
python3 scripts/reverse_video.py --prod productions/<slug> --video /path/to/ref.mp4 --localize --no-grok
python3 scripts/check_prod.py --prod productions/<slug>
python3 scripts/render_blocking.py --prod productions/<slug>
python3 scripts/render_shots.py --prod productions/<slug> --only SH001 --review-track
```

## 命名

```
角色主图      02-assets/characters/<slug>/master.jpg
场景空镜      02-assets/scenes/<slug>/master.jpg
舞台机位      02-assets/scenes/<slug>/blocking.jpg
分镜合同      03-storyboard/shots.json
场次舞台      03-storyboard/sets.json
首帧          04-frames/SH001.jpg
上一镜末帧    04-frames/SH001-last.jpg
单镜视频      05-shots/SH001.mp4
审剧情        06-export/preview-30s-vo.mp4
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

1. 先写 `sets.json` 和 `coverage.md`。都市短剧 **6–10 镜、50–75 秒**。神话旁白集仍可 8–15 镜、70–90 秒。
2. 单镜 **6 秒优先**。覆盖需要时 close 可以短于 master，不要为均分而 6+6+6。
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
7. 不赌对白口型。角色参考图仍校验存在；CompShare 提交时丢掉参考图。
8. 默认 Hailuo Fast 无声；`tier=h3` 每集不超过 3 镜。

### 旁白与声音

1. 都市短剧：C2 就写 `line` / `caption` / `line_kind` / `speaker`。种类是口述、心里、旁白、出场简介、短信。出完画面立刻 `mix_review_track.py`。
2. 神话集：整段一次 TTS，画面跟人声气口走。见 `productions/khmer-stories/SOUND.md`。
3. 成片高棉语是 Gate F，中文工作轨是 Gate E+。两套都要，不能用工作轨冒充成片。
4. 都市短剧走无声画面配音：`scripts/dub_silent_episode.py`。先有 `06-export/ep01.mp4`，再克隆。见 `DUBBING.md`。
5. **R12** BGM 高棉流行或婚礼锣鼓。H3 人声不当配音。云端出的环境声也不当成品声。
6. **R1–R2** 人名不译。


## 导演台入口

本机 UI 把上述关卡做成可点的锁定轨，源文件仍是本目录结构。启动：`bash scripts/run_director.sh`。详见 `STUDIO.md`。


脚本专家（导演台剧本页）只写 `*.draft.*`。优先把已有 `coverage.md` 编译成 6–10 镜合同，运镜句来自 `templates/camera-moves.md`，不另造一套 MJ/SD 提示词。正式分镜仍要人审 + `check_prod.py`。

导演层细则见 `DIRECTOR.md`。拆镜 Agent 按场合同出草稿：2–3 个机位、对白镜短、提示词含本镜动作。覆盖表是证据，不是一行一镜。
