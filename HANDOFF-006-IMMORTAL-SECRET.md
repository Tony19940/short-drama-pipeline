# 006《长生秘密》项目交接文档

更新时间：2026-09-01  
项目状态：资产准备中，尚未进入正式拆镜、关键帧或视频生成

## 一句话结论

006《长生秘密》的故事关和编剧关已经锁定，9 个角色的 `master.jpg` 与 `face.jpg` 已齐，8 个场景还差 1 个空镜。当前没有可出片的完整分镜、舞台点位、首帧、单镜视频或成片。下一步应先补完资产和 `blocking.jpg`，再让导演 Agent 按第 01 集剧本重新拆镜。

不要把 `03-storyboard/shots.json` 误认为已完成：它目前只有 1 个旧占位镜头 `SH001`，不是第 01 集正式分镜表。

## 1. 总目录位置

本机整条流水线根目录：

```text
/Users/tony/vibe coding/short-drama-pipeline
```

006 项目目录：

```text
/Users/tony/vibe coding/short-drama-pipeline/productions/006-immortal-secret
```

本机导演台：

```text
UI   http://127.0.0.1:3101
API  http://127.0.0.1:18765
健康 http://127.0.0.1:18765/api/health
```

当前 UI 和 API 都已启动。若重启机器或服务，进入流水线根目录执行：

```bash
cd "/Users/tony/vibe coding/short-drama-pipeline"
bash scripts/run_director.sh
```

如果 3101 或 18765 已经有服务在监听，不要重复启动，直接打开上面的 UI 地址并用健康接口检查。

## 2. 目录与职责

| 位置 | 作用 | 006 当前情况 |
|---|---|---|
| `01-bible/source/` | 故事源，保存原始小说及来源信息 | 已有 `original.md`、`source.json` |
| `01-bible/` | 剧本、系列设定、画幅和文化确认 | 五集剧本及确认文件已在 |
| `01-bible/producer/` | 制片缺口清单和任务单 | 有 `plan.draft.md`、`manifest.draft.json`，尚未作为完成态 |
| `02-assets/LOOK.md` | 全片画风、画幅、光影和禁止项 | 已有，当前为写实电影、雨季柬埔寨、9:16 |
| `02-assets/characters/` | 角色主图、脸图、联络板 | 9 个角色已有主图和脸图，联络板都缺 |
| `02-assets/scenes/` | 场景空镜及场景说明 | 8 个场景中 7 个已有主图 |
| `02-assets/props/` | 道具主图 | 4 件道具都缺主图 |
| `03-storyboard/sets.json` | 每场空间轴线、站位和机位点 | 已有 8 场点位草稿，但还没有 blocking 图 |
| `03-storyboard/beats.md` | 第 01 集剧情节拍和新信息 | 已有 8 个节拍 |
| `03-storyboard/coverage.md` | 每场采用哪些覆盖机位 | 已有 8 个场次草稿 |
| `03-storyboard/shots.draft.json` | 导演 Agent 拆出的待审镜头清单 | 当前不存在 |
| `03-storyboard/shots.json` | 人接受后的正式旧分镜合同 | 只有 1 个旧占位镜头，不可用于出片 |
| `.pipeline/` | 新 11 岗交接 JSON | 当前不存在，尚未启动新项目交接合同 |
| `.director/` | 旧导演台审批、任务、候选和备份 | 有 `approvals.json`、`inbox/`、`candidates/`、`backups/` |
| `04-frames/` | 人审通过的逐镜首帧和设计尾帧 | 为空 |
| `05-shots/` | H3 或其他视频模型输出的逐镜视频 | 为空 |
| `06-export/` | 审片轨和最终成片 | 为空 |
| `07-narration/` | 旧旁白目录 | 为空 |
| `08-qc/` | 新流程质检报告 | 当前不存在 |

## 3. 当前关卡状态

审批记录在：

```text
/Users/tony/vibe coding/short-drama-pipeline/productions/006-immortal-secret/.director/approvals.json
```

目前只有以下两关锁定：

| 关卡 | 名称 | 状态 | 说明 |
|---|---|---|---|
| Gate 0 | 小说 | 已锁定 | 故事源已归一到 `01-bible/source/` |
| Gate A | 编剧 | 已锁定 | 剧本、确认、蓝图齐全 |
| Gate B | 资产 | 未锁定 | 缺 `bangkok-office/master.jpg` |
| Gate C | 分镜 | 未开始 | 缺 `blocking.jpg`，且正式分镜只有占位镜头 |
| Gate C1 | 说明书 | 未开始 | 不能沿用当前占位分镜作为完整说明书 |
| Gate C2 | 生成包 | 未开始 | `.pipeline/` 生成包尚未建立 |
| Gate D | 关键帧 | 未开始 | 缺 `SH001` 及后续所有正式首帧 |
| Gate E | 视频 | 未开始 | 没有单镜视频 |
| Gate E+ | 声音 | 未开始 | 没有带声带字审片轨 |
| Gate F | 剪辑 | 未开始 | 没有 `06-export/ep01.mp4` |

制片缺口草稿刚刚按磁盘状态刷新，当前 14 项：

```text
9 个角色联络板：lin / sara / baset / somchai / anu / chongde / chenmo / dean / yiey
1 个场景空镜：bangkok-office/master.jpg
4 件道具主图：chongde-photo / eyeless-map / jin-powder / oilcloth-packet
```

制片草稿位置：

```text
productions/006-immortal-secret/01-bible/producer/plan.draft.md
productions/006-immortal-secret/01-bible/producer/manifest.draft.json
```

角色联络板和道具是关键帧阶段的必要参考；它们不是 Gate B 当前唯一的阻塞原因，但不补齐就不应开始正式关键帧生产。

## 4. 已有剧本和设定文件

主要文件：

```text
productions/006-immortal-secret/01-bible/series-bible.md
productions/006-immortal-secret/01-bible/CAST.md
productions/006-immortal-secret/01-bible/confirm.md
productions/006-immortal-secret/01-bible/blueprint.md
productions/006-immortal-secret/01-bible/CULTURE-CHECK.md
productions/006-immortal-secret/01-bible/STATUS.md
productions/006-immortal-secret/01-bible/ep01.md
productions/006-immortal-secret/01-bible/ep02.md
productions/006-immortal-secret/01-bible/ep03.md
productions/006-immortal-secret/01-bible/ep04.md
productions/006-immortal-secret/01-bible/ep05.md
```

第 01 集为《无眼之墙》，当前已准备 8 个场景：1961 丛林溪谷、大学办公室、村落入口、丛林山脊、遗址外墙、遗址前厅、巴瑟公寓、曼谷办公室。节拍目标约 90 秒，开场要求在 0–8 秒出现凿眼与水声。

## 5. 资产命名规则

所有正式资产都必须放进 006 项目，不要只留在 Codex 的生成图片目录：

```text
角色主图：02-assets/characters/<slug>/master.jpg
角色脸图：02-assets/characters/<slug>/face.jpg
角色联络板：02-assets/characters/<slug>/sheet.jpg
角色三视图：02-assets/characters/<slug>/front.jpg
            02-assets/characters/<slug>/side.jpg
            02-assets/characters/<slug>/back.jpg
场景空镜：02-assets/scenes/<slug>/master.jpg
舞台点位：02-assets/scenes/<slug>/blocking.jpg
道具主图：02-assets/props/<slug>/master.jpg
```

当前已经生成的角色主图和脸图不要换脸。`face`、`sheet`、正侧背都从对应 `master` 修改，不能另开一个新角色。

把 Codex 生成的图放进项目时使用：

```bash
python3 scripts/place_codex_asset.py \
  --prod productions/006-immortal-secret \
  --kind character \
  --slug dean \
  --slot sheet \
  --src "/path/to/generated.png"
```

`--kind` 可用 `character`、`scene`、`prop`。具体角色或场景卡先读：

```text
productions/006-immortal-secret/02-assets/characters/<slug>.md
productions/006-immortal-secret/02-assets/scenes/<slug>.md
productions/006-immortal-secret/02-assets/props/<slug>.md
productions/006-immortal-secret/02-assets/LOOK.md
```

场景主图必须是空镜，不放人物。完成所有场景主图后生成舞台点位：

```bash
python3 scripts/render_blocking.py \
  --prod productions/006-immortal-secret
```

## 6. 正确的后续流水线

导演台顶部的 10 个内容岗是：

```text
小说 → 编剧 → 资产 → 分镜 → 说明书 → 生成包 → 关键帧 → 视频 → 声音 → 剪辑
```

另有制片统筹，负责缺口、放行和打回，不代替其他岗位创作。

每一岗的实际交接文件如下：

| 岗位 | 交接内容 | 主要真源 |
|---|---|---|
| 小说 | 原始小说、故事设定 | `01-bible/source/` |
| 编剧 | 系列圣经、分集大纲、分场剧本、台词 | `01-bible/` |
| 资产 | 角色、场景、道具及其身份锁 | `02-assets/` |
| 分镜 | 这场拍哪些镜、谁在左、谁看谁、每镜任务 | `03-storyboard/sets.json`、`beats.md`、`coverage.md`、`.pipeline/shot_list.json` |
| 说明书 | 每镜中文的人类可读拍摄说明 | `.pipeline/shot_specs.json` |
| 生成包 | 给目标视频模型的逐镜生成计划 | `.pipeline/gen_packages.json` |
| 关键帧 | 本镜第 0 秒构图，父图和参考图 | `04-frames/`、`.pipeline/keyframes.json` |
| 视频 | 按镜生成的真实 mp4 | `05-shots/`、`.pipeline/clips.json` |
| 声音 | 台词、旁白、环境声和审片轨 | `07-narration/`、`06-export/preview-*-vo.mp4` |
| 剪辑 | 人审后的进出点、删镜和成片 | `.pipeline/cut.json`、`06-export/ep01.mp4` |

关键原则：分镜设计先决定“拍什么”，说明书再写“怎么拍”，生成包再翻译成模型输入，不能让一个函数一次性把三层内容全部写完。首帧只负责第 0 秒的站位和构图；动作过程写在视频提示词里。视频按单镜生成，最后由剪辑时间线裁剪，不把多张静帧直接串成成片。

## 7. Agent 知识库位置

岗位提示词和交接字段表在：

```text
knowledge/pipeline-pack/短剧流水线_Agent岗位说明书.md
knowledge/pipeline-pack/改造总令.md
knowledge/pipeline-pack/交接字段表.md
knowledge/pipeline-pack/prompts/00_制片统筹.md
knowledge/pipeline-pack/prompts/01_小说.md
knowledge/pipeline-pack/prompts/02_编剧.md
knowledge/pipeline-pack/prompts/03_视觉资产.md
knowledge/pipeline-pack/prompts/04_分镜设计.md
knowledge/pipeline-pack/prompts/05_分镜说明书_5.1.md
knowledge/pipeline-pack/prompts/06_生成包_5.2.md
knowledge/pipeline-pack/prompts/07_关键帧_6.1.md
knowledge/pipeline-pack/prompts/08_视频生成_6.2.md
knowledge/pipeline-pack/prompts/09_声音.md
knowledge/pipeline-pack/prompts/10_剪辑.md
```

导演层参考：

```text
knowledge/director/playbook.md
knowledge/director/coverage.md
knowledge/director/motion.md
knowledge/director/grid.md
knowledge/director/blender.md
knowledge/cases/escape.md
knowledge/cases/reveal.md
knowledge/cases/send-off.md
knowledge/cases/standoff.md
```

编剧、资产和声音知识分别在 `knowledge/writer/`、`knowledge/art/` 和 `knowledge/sound/`。这些文件是岗位 Agent 的规则和参考资料，不是 006 的正式剧情文件。

## 8. 文本模型、图片和视频的边界

文本 Agent：

- `xai/grok-4.6` 只负责读剧本、改写或填写结构化文本。
- 本机优先通过 Grok/OpenCodex 订阅代理调用，默认地址是 `http://127.0.0.1:10100/v1`。
- 当前健康检查显示 `grok_text=true`、`grok_backend=grok-subscription`，所以分镜等文字 Agent 可以继续使用。
- 不要把 Grok 订阅额度写成 `XAI_API_KEY`，也不要把订阅信息写进交接文档。

图片：

- 当前主路径是 Codex 内置 imagegen 生成或编辑，再用 `place_codex_asset.py` 放入 006。
- `grok-4.6` 不是图片模型。
- 当前健康检查显示 `imagine=false`，表示没有启用 `XAI_API_KEY` 的 Imagine API；这不影响人工把 Codex 生成图放入项目。

视频：

- 本机导演台只派发单镜任务，不假装本地完成。
- 云端合同是 `POST /v1/i2v` 和 `GET /v1/i2v/{task_id}`。
- 适配器在 `scripts/video_backends/runpod_i2v_server.py`，本地调用封装在 `scripts/video_backends/local_h3.py`。
- `image_b64` 是锁定首帧；同场、同机位且人物有交集的续镜才允许用上一镜真实末帧；参考图挂在首帧外面。
- 没有可用 GPU 时，任务必须保持 `queued`，不能用 Ken Burns 或静帧动效冒充视频。

## 9. 当前 GPU 状态

`.env` 中已经有 `LOCAL_H3_BASE` 配置，但本次实际检查结果是 GPU 健康探测连接被拒绝。也就是说：环境变量“已配置”，GPU 服务“当前不可达”，不能据此判断 H3 已经能出片。

敏感配置只存在本机 `.env` 或云端服务，不把值写进交接文档。可能涉及的变量名包括：

```text
LOCAL_H3_BASE
LOCAL_H3_TOKEN
MINIMAX_API_KEY
COMPSHARE_API_KEY
XAI_API_KEY
GROK_SUBSCRIPTION_BASE
```

换新服务器时，只需要让新机器重新部署 H3 推理服务，并保持 HTTP 合同；本地导演台仍使用同一个 `LOCAL_H3_BASE`。检查：

```bash
curl -s http://127.0.0.1:18765/api/health
curl -s http://127.0.0.1:18765/api/gpu
```

当前健康接口还显示 `gpu=true`，这是“检测到 `LOCAL_H3_BASE` 非空”；`/api/gpu` 的实际连接检查才是判断 GPU 是否可用的依据。

## 10. 接手后的第一组动作

按以下顺序继续：

1. 补 `02-assets/scenes/bangkok-office/master.jpg`。
2. 补 4 件道具主图和 9 个角色 `sheet.jpg`，全部从已锁主图或道具设定制作。
3. 重新生成制片缺口清单，确认 14 项归零：

   ```bash
   python3 - <<'PY'
   import sys
   sys.path.insert(0, "scripts")
   from director.paths import productions_root
   from director.producer import write_producer_draft
   write_producer_draft(productions_root() / "006-immortal-secret")
   print("producer draft refreshed")
   PY
   ```

4. 生成并人工检查 8 个场景的 `blocking.jpg`。
5. 在导演台分镜页运行导演 Agent，生成 `shots.draft.json`；人先看整集节奏和空间关系，再接受正式分镜。
6. 生成 C1 说明书和 C2 生成包，确认每镜的动作、景别、运镜、声音、父图、参考图和模式。
7. 按镜从父图生成首帧，首帧过人工 QC 后才锁 Gate D。
8. GPU `/v1/i2v` 可达后，再按镜派 H3；完成视频 QC 后才做声音和剪辑。

## 11. 验证命令

检查当前旧分镜合同：

```bash
python3 scripts/check_prod.py \
  --prod productions/006-immortal-secret
```

当前该命令预期失败，因为还缺 `blocking.jpg`，且现有 `shots.json` 只是占位。这个失败是正确的阻断，不要用跳过检查的方式出片。

回归测试：

```bash
python3 -m unittest scripts.tests.test_director
```

查看资产目录：

```bash
find productions/006-immortal-secret/02-assets -type f | sort
```

查看 006 项目状态：

```bash
curl -s http://127.0.0.1:18765/api/productions/006-immortal-secret
```

## 12. 相关项目和边界

同一仓库里的其他生产资料：

```text
productions/003-sreymom-engagement
productions/004-yuye-jinlian
productions/005-defeat-named
productions/_template
productions/khmer-stories
```

003、004、005 是既有样片和回归参考，不要拿它们的旧 `shots.json` 自动覆盖 006，也不要改动它们的正式成片。`_template` 是新项目空壳，`khmer-stories` 是故事总簿。

旧的云端交接资料在：

```text
cloud-handoff/
```

它主要记录既有项目的云端任务，不等于 006 已经部署好的 GPU。006 的真源始终是本机 `productions/006-immortal-secret/`。

声音项目目录：

```text
/Users/tony/Documents/高棉配音真人剧
```

006 还没有进入高棉配音阶段，暂时不要把声音库或外部配音成品当作本项目已完成的声音关卡。

## 13. 交接注意事项

- 根目录当前不是 Git 工作树；交接时应复制整个 `/Users/tony/vibe coding/short-drama-pipeline`，不要只复制 006 子目录。若之后需要版本管理，应先另行初始化或建立备份策略。
- `.env`、`.inkos/secrets.json` 可能含本机凭据，不要上传、转发或写入公开仓库。
- 资产图、舞台图、首帧、视频和 JSON 的“草稿 / 候选 / 正式 / 锁定”状态不同，不能因为文件存在就视为已通过人工审核。
- 修改上游正式文件后，下游关卡必须重新检查；不要直接继续使用旧首帧或旧视频。
- 任何进入 `06-export/` 的文件都必须是真实 mp4，不能是 Ken Burns、静帧串联或无声假审片轨。
