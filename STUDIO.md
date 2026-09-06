# 本机导演台

控制台直接读写 `productions/`，不走巨日禄积分，也不写第二套数据库。交接 JSON 在 `.pipeline/`，图和视频仍在 02-assets / 04-frames / 05-shots / 06-export。

```
bash scripts/run_director.sh
```

- UI：[http://127.0.0.1:3101](http://127.0.0.1:3101)
- API 健康检查：[http://127.0.0.1:18765/api/health](http://127.0.0.1:18765/api/health)

v3 主验收是 `004-yuye-jinlian` 第 01 集。导演台默认打开 004。`003` 只跑回归。

## 操作流

顶栏是 1→10 的一条路径：小说 → 编剧 → 资产 → 分镜 → 说明书 → 生成包 → 关键帧 → 视频 → 声音 → 剪辑。制片统筹只做放行/打回。缺口清单并进资产页。打开项目会落在下一步该做的关，底栏主按钮是「锁定，进入下一步」。差异和退回藏在「更多」。

反推页仍隐藏，文件在 `00-reverse/`。故事关是新的 Gate 0，目录 `01-bible/source/`。

每关四种状态：等待上一步 / 草稿待审核 / 已锁定 / 上游已修改。上游正式文件改了，下游 stale，不能未重审派出 H3。

| 页 | 干什么 | 这一步点哪个 |
|---|---|---|
| 小说 | 写或上传故事 | 启动 InkOS 或上传 md/txt |
| 编剧 | 改能拍的分场本 | 保存台词和场次；不写景别运镜 |
| 资产 | 锁脸/空镜/道具 | 按缺口清单把图放进 02-assets |
| 分镜 | 决定拍哪些镜头 | 先舞台，再按场拆镜头清单 |
| 说明书 | 7 组人读说明 | 保存；台词必须是编剧原句 |
| 生成包 | 模型计划 | 人点确认后才能出关键帧/视频 |
| 关键帧 | 这一镜静帧 | 从父图改，过审再往下 |
| 视频 | 单镜出片 | 先预览再派出；未确认生成包不能派 |
| 声音 | 原句配音 | 叠工作旁白听一遍 |
| 剪辑 | 时间线成片 | 按说明书秒数修剪，可删镜 |

导演页先看整场节奏板，再点「按场拆镜」。拆镜只写草稿。人接受后才进正式表。详见 `DIRECTOR.md`。

每关要人点锁定。未过 `check_prod.py` 不能出视频。AI 只写草稿。旧项目（如 004）没有 `source/` 时故事页只读展示已迁移剧本，不改写 `ep01.md` / 资产 / 8 镜。

外部 skill 压进 `knowledge/` 分层加载：编剧看开场/钩子，导演看运镜和宫格，美术看联络板，声音看怎么念。宫格只给人看整场，不拿去出片。宣传片一键成片和可灵出片口不进主路径。

## 导演层

- 一场一条轴，先有 `sets.json` 和 `blocking.jpg`。
- 覆盖至少 master + 更紧的机位。
- 邻镜只改一件事。同场续镜从父镜改静帧。静帧只画 `start`，不要把整段动作贴进生图。
- 出片时永远锁首帧（FL2VA）。同机位且人物有交集才吃 `{from}-last.jpg`；换机位或切到另一人，用这一镜锁定首帧。
- 动作要收住时，分镜写设计尾帧 `end_frame`（如 `04-frames/SH004-end.jpg`），不能拿生成后抽出的 `{id}-last.jpg` 冒充。
- 角色 `sheet.jpg` / `face.jpg` 只作为 Ref2VA 外挂锁脸，不替代第 0 秒。换 GPU 也拷同一份 `runpod_i2v_server.py`。

## 模型

- `xai/grok-4.6` 只写导演文本，不当生图模型。
- 静帧走 Grok Imagine（`XAI_API_KEY`，默认 `grok-imagine-image-2.0`）。没有密钥时仍可人工上传，但必须挂父图。
- 视频走 `LOCAL_H3_BASE` 的 `POST /v1/i2v`。没接 GPU 时任务停在 queued，不假装成功。

## 禁止

Ken Burns / `stills-to-shots.sh` 不是成片路径。该脚本已挪到 `scripts/_disabled/`。`assemble.sh` 会拒绝 `*kenburns*` / `*still-pass*`。

## v2 人审分镜合同

分镜页是剪映式审片台：左剧本、中镜头条、右本镜说明书。  
`video_prompt` 才是给模型的镜头指令；对白只写在 `line` / `caption`。

出图默认丢 `.director/inbox/`：

1. 在分镜页点「复制出图任务」
2. 把生成的图按 `SH002.jpg` 或 `character-sreymom-sheet.jpg` 丢进来
3. 点「扫描收到的图」：只进候选，不自动覆盖正式文件
4. 首帧页锁定后才写入 `04-frames/` 或资产目录

旧 `master` / `face` 和现有 9 张海报可留对照。新首帧必须挂 `sheet.jpg`。没有 GPU 时出片仍停在 queued。


## v3 可审出片

- 分镜页「先审查」只写 `03-storyboard/review.draft.md`，不改 `shots.json`，也不挡「接受正式表」。
- H3 编译：先声明 Picture 1 对齐 0.00 秒（有设计尾帧则 Picture 2 对齐片尾秒数），再写三字段 `integrated_multimodal_description` / `overall_soundscape` / `non_diegetic_music: N/A`。正文按第 0 秒 → 一次动作 → 收住。sheet/face 只锁身份。对白仍只在 `line` / `caption`。
- 出片页先「先预览」再「确认并派出」。改分镜、换父图、失败重试都要重新确认。
- 审剧情先冻 `.director/review-contract.json`。缺声、缺字、Ken Burns 都不能标 pass。没有视觉模型时结论是 `inconclusive`。


## Gate 0 · 反推

上传一条现成短剧，拆成可审分镜草稿，再改成柬埔寨故事。源文件在 `00-reverse/`，镜头草稿在 `03-storyboard/shots.draft.json`。

1. 导演台选/新建项目，打开「反推」
2. 上传本地 mp4（不解析抖音/小红书链接）
3. 点「分析成草稿」：ffmpeg 切镜、抽中点帧、可选 whisper 转写、Grok 写说明书（没密钥就用切镜草稿）
4. 点「改成柬埔寨」：人名、地点、服装按 `CULTURE.md` 改写，对白仍在 `line`/`caption`
5. 到分镜页看草稿，改画面句 / 轴 / 运镜
6. 舞台和资产齐了，再「接受正式表」。未过 `check_prod.py` 不会覆盖 `shots.json`

命令行：

```bash
python3 scripts/reverse_video.py --prod productions/<slug> --video ~/Desktop/ref.mp4 --localize
```

反推不是出片。没有 blocking、没有联络板、没有人锁 Gate C，仍然不能生成视频。


## 脚本专家（写分镜，不出片）

剧本页的「写分镜草稿」走鹏城六步，但落地到本机合同：

1. 理解需求 → 读 `confirm.md` / `ep01.md`（金边竖屏，不对口型）
2. 规划结构 → `01-bible/blueprint.draft.md`（3 秒钩子 / 中段冲突 / 尾钩，不写广告号召）
3. 生成分镜 → 先吃已有 `coverage.md` / `beats.md`，再写 `03-storyboard/shots.draft.json`
4. 撰写提示词 → 每镜英文 `video_prompt`，读 `templates/video-prompt-formula.md` + `templates/camera-moves.md`（H3 / Imagine，不是 MJ/SD/`--ar`）
5. 编写文案 → `voiceover.draft.md` + `line` / `caption` / `emotion`
6. 自检交付 → 对白不准进 `video_prompt`；人在分镜页接受后才进正式表

角色 slug 必须对上 `02-assets/characters/`。004 的罗丝是 `ros`，不是 `yeay-ros`。  
资产任务单读 `templates/character-sheet-prompt.md`：正侧背和 sheet 从 `master` 改。  
专家只写草稿。没有 blocking、没有人锁 Gate C，仍然不能出视频。
