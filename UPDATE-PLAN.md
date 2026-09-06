## Gate 0 已落地

导演台可上传参考片，切镜+转写写成 `shots.draft.json`，再改成柬埔寨故事。正式 `shots.json` 仍要人接受且过 `check_prod.py`。不解析抖音链接，不一口生成整集。

# 导演台 v2 更新计划

## 已落地（本机 v2）

- `shots.json` 每镜已有 `lens` / `axis` / `camera` / `action` / `look` / `video_prompt` / `negatives`
- 003 / 002 都市短剧合同已通过 `check_prod.py`
- 导演台覆盖/分镜页改成左剧本、中镜头条、右说明书
- 出图任务单写入 `.director/inbox/`；扫描后只进候选
- 新首帧缺 `sheet.jpg` 不能锁定；正侧背从 master 改
- `render_shots.py` 出片用编译后的 `video_prompt`，不再只用短 `prompt`


把「可借鉴的外部做法」和本机 `003` 第 01 集接到同一条人审流水线上。  
源文件仍是 `productions/`。不换巨日禄，不把 Comfy 画布当成真相，不一口生成整集。

当前缺口不是缺页面，而是分镜合同太薄：`shots.json` 的 `prompt` 还是一句 `Close-up. ... [Push in]`，角色只有 `master.jpg` + `face.jpg`，没有多视图，也没有给视频模型的完整镜头说明书。人审关卡已有，审的对象不够导演。

## 原则

1. **分镜表是人审合同，也是视频模型的提示词。** AI 只写草稿。人点锁定之前，不准生首帧、不准出视频。
2. **一致性靠资产，不靠模型记忆。** 角色和场景先出多视图，后续只从这些图改。
3. **一镜一个运动、一场一条轴。** 禁止九宫格一镜直出整集，禁止 Ken Burns，禁止用 Bridge 洗坏切。
4. **Grok 文本 ≠ Grok 像素。** `grok-4.6` 写分镜/编译提示词；像素走 Imagine 或已登录的 Grok 网页。视频走云 GPU 上的 MiniMax-H3。
5. **高棉语短剧不对口型赌成片。** 示范长提示词里的「原生同步对白」只学其镜头写法，不改 R12。

## 截图里那套工作流是什么

那是 **ComfyUI 资产图**，不是一键成片器。

能读到的结构：

- 左：场景包、车辆、城市空镜
- 中：`人物` 多宫格（正/侧/表情/全身）、双人定妆、`PhotoStudio` 棚内光
- 右：大量 `Video` 节点，从同一批人物/场景图拉线出去

它在做的事：先建角色和场景图书馆，再按镜实例化视频。这和我们「Gate B 资产 → Gate D 首帧 → Gate E 单镜」是同一类。

直接搬：多视图角色板、场景包命名、人物图当所有 Video 节点的父资产。  
不搬：用节点连线当项目数据库。本机真相仍是文件夹。那张「蜘蛛网」就是素材一散、角色就会漂的现场。

## 从那条 30 秒家庭争吵提示词里学什么

学的是 **分镜密度**，不是「一条提示词出 30 秒成片」。

它真正值钱的结构：

1. 先锁世界：画幅、胶片感、年代、光线、色板、禁止项
2. 再锁人物：年龄、种族、服装、声音、站位、180 度轴线
3. 然后按时间写每一镜：焦段、景别、构图、运镜、表情、台词、硬切点
4. 声音和环境单独一节，不和画面混写成形容词
5. 负面清单写死：不换装、不漂脸、不环绕、不字幕、不第三人

对照 003 现在的 SH002：

```
Close-up. The fashionable woman glances aside once, jewelry still. [Push in]
```

这不够给视频模型当导演指令。人审通过的分镜，至少要写到示范提示词那种粒度，但 **按镜切开**，不要把 9 镜 65 秒塞进一条。

示范片里不要学的：

- 20:9 宽银幕（我们锁 9:16）
- 30 秒一次生成四镜（我们按镜出，continue 吃末帧）
- 原生口型英语对白当成品（我们：画面默认无口型，台词进 `line`/`caption`，高棉语成片在 Gate F）
- FACS 编号可作表演备注，不作为 H3 必填字段

## 从 FiniYang 帖学什么

[FiniYang / recurring-character-diary-comic](https://x.com/FiniYang/status/2091386966504071672) 讲的是连续角色日记漫画，但验收逻辑可直接借到短剧：

- 没有锁定角色参考，不准开始
- 先锁故事脊柱和节拍，再写长提示词
- 把要求分成三等：S0 故事真相、S1 身份身体、S2 表现选择。S0/S1 错了整镜失败
- 空间关系要证明，不能「同框」就算过（谁在左、谁看谁、托盘朝哪、合十朝谁）
- 对白逐字正确；错一个字就失败
- 默认整场/整页生成连续性，失败才局部修；compositor 是兜底，不是导演
- 风险高时不要自动拆成互不相干的单图

对我们：Gate B 没锁不准写 C；Gate C 没锁不准 D/E。首帧从 blocking/父镜改，而不是九张新海报。字幕和人名走 S0。

## 别人那套四步流水线和 Comfy 作业

四步（剧本分镜 → 定妆场景 → 按镜视频 → 拼接配音）我们已经有。要吸收的是纪律，不是再找一个 LocalMiniDrama / Jellyfish / Toonflow 替换导演台。

Comfy + H3 作业的链：

```
设定图 → MiniMax 提示词 Skill → 故事板静帧 → Comfy 出视频
```

对应我们：

```
多视图资产 → grok-4.6 写分镜表草稿 → 人审锁定 → Grok 出首帧 → GPU H3 出单镜
```

Jellyfish 的 ControlNet/全局种子、Toonflow 无限画布、H3「小说进、成片出」，都不替代人审分镜表。封面透明字图层可以以后做导出，不是 003 第 01 集的门。

## 目标工作流（人在回路）

```
剧本 ep01.md
    │  grok-4.6 草稿，人改
    ▼
[Gate A]  confirm / blueprint / 文化勾选
    │
    ▼
[Gate B]  角色多视图 + 场景多视图 + 身高图
    │  Imagine 或 Grok 网页；只许 master 全新一次
    ▼
[Gate S]  sets.json 打点 → blocking.jpg
    │
    ▼
[Gate C]  覆盖表 + 分镜表（人审）
    │  每镜：景别/焦段/轴线/运镜/表演/台词/video_prompt
    │  check_prod.py + Prompt Check 都过，人才锁定
    ▼
[Gate D]  首帧：从 blocking 或上一镜改，多视图当参考
    │
    ▼
[Gate E]  单镜视频：I2V / FLF / 末帧续；最多 3 条 H3
    │
    ▼
[Gate E+] 带声带字审剧情（中文工作轨）
    │
    ▼
[Gate F]  高棉语成片（下一期）
```

剪映脚本编辑器：只借鉴「左剧本、中镜头条、右镜头说明书、时间线预览」。不登录剪映当生产依赖。浏览器去操作剪映是备选，不是 v2 默认。

## 分镜表合同（v2 核心）

`03-storyboard/shots.json` 每镜在现有字段之外增加（缺省则 Gate C 不能锁）：

| 字段 | 作用 |
|---|---|
| `lens` | `35mm` / `50mm` / `85mm` |
| `axis` | `left` / `right` / `center`；同场遵守 180 度 |
| `camera` | 一句：固定 / 呼吸手持 / 慢推 / 一次横摇 |
| `action` | 这几秒身体做的一件事 |
| `look` | 光线、背景虚实、站位，必须能对上 blocking |
| `video_prompt` | 编译给 H3/Imagine 的英文镜头说明书 |
| `negatives` | 本镜禁止项（换装、第三人、环绕、字幕） |

人在导演台看到的「剪映分镜表」就是这些字段的表 + 缩略图 + 父镜。  
`prompt` 保留为短句；真正出片用 `video_prompt`。  
AI 写到 `03-storyboard/shots.draft.json`，人接受后才覆盖正式文件。

`check_storyboard.py` 新增：

- `video_prompt` 非空，且包含景别或 `setup`、以及 `move` 对应的运镜词
- `action` 与 `new_info` 不是同一句空话
- 同场 `axis` 不跳轴，除非 `cut=hard` 且换场
- `camera` 与 `move` 一致（`static` 不得写环绕/快推）
- 对白在 `line`，禁止把字幕写进 `video_prompt`

## 多视图资产

角色目录补齐（卡片模板里已有，工程里还没强制）：

```
02-assets/characters/<slug>/
  master.jpg   face.jpg
  front.jpg    side.jpg    back.jpg
  sheet.jpg    # 2×3 或 3×2 联络板，给 Grok/H3 当参考
```

场景：

```
02-assets/scenes/<slug>/
  master.jpg          # 空镜
  door.jpg table.jpg  # 从 master 改的机位，不是新房间
  blocking.jpg
```

Gate B 锁定条件：每个出场角色有 master+face+至少正侧；有双人戏有 `scale.jpg`；每场有 master+blocking。  
`sheet.jpg` 由正侧背合成，禁止另开一张全新脸拼进去。

## 出图路径

顺序：

1. 导演台生成「出图任务单」：目标路径、父图、参考图、提示词、禁止项
2. 有 `XAI_API_KEY`：Imagine 出候选，人审后锁定
3. 没有密钥：复制任务单，人在已登录 Grok 网页出图，上传候选（仍必须挂父图）
4. 浏览器自动点 Grok：**v2 不做默认**。等任务单格式稳定再加 Chrome 控制；失败必须可手传

禁止：用 `grok-4.6` 直接当生图模型；没有父图的非 master 生成。

## 出视频路径

`LOCAL_H3_BASE` 扩成四种 mode，仍是一个 HTTP 合同：

| mode | 何时 |
|---|---|
| `i2v` | 开场/硬切，只有锁定首帧 |
| `flf` | 同场续且已有目标姿态/末帧 |
| `r2v` | 需要锁脸时带 `face.jpg`/`sheet.jpg` |
| `extend` | 明确要从上一镜视频续，而不是新海报 |

GPU 上可挂 javawock 的 Comfy 图，但导演台只发任务，不编辑节点。  
H3 人声不当配音轨。Face Refine 只修一镜近景。Bridge 默认关。

## 导演台界面

现有关卡轨保留。覆盖/分镜页升级成脚本编辑器：

- 左：`ep01.md`
- 中：镜头条（缩略图、秒数、setup、move、父镜、锁定点）
- 右：本镜说明书（表演、轴线、`video_prompt`、参考图）
- 底：可选时间线，只能播已出的 mp4 + 审片轨

资产页展示多视图联络板，不展示积分。  
首帧页继续：左父图、右候选、锁定才覆盖 `SH00N.jpg`。

不把 Cloudflare 复刻站当生产面。

## 分期（只服务 003 第 01 集）

**P0 分镜表可审**

- 扩展 `shots.json` 与 `check_storyboard.py`
- 导演台分镜表 UI：人能改、能锁、能看父镜
- grok-4.6 只写 `shots.draft.json`；人接受才进正式表
- 把 003 现有 9 镜补成完整 `video_prompt`（人审一次）

**P1 多视图资产**

- 角色/场景出正侧背和 sheet
- Gate B 强制检查
- 出图任务单 + Imagine/人工上传

**P2 按合同出片**

- `video_prompt` → I2VA/FL2VA 编译（可先用 HF 那两份系统提示词）
- GPU mode：i2v/flf/r2v
- 审剧情轨仍走 `mix_review_track.py`
- 旧 9 张海报首帧可保留对照，默认按父镜重做，不自动当合格连续性

**P3 不做**

- 剪映登录自动化
- 浏览器 Grok 默认出图
- 九宫格一镜直出 65 秒
- 对口型高棉语成片
- Comfy 无限画布当项目库
- 整集一条提示词

## 验收

- 人能在 3101 打开 003 九镜分镜表，改一镜 `video_prompt`/`camera`，未过检查则回滚
- 未锁定 Gate C，出图/出片接口 409
- 缺 `front.jpg` 时 Gate B 不能锁（新工程）；003 补齐后再锁
- SH002 的 `video_prompt` 含景别、慢推、姐姐站位、一句动作，且对白只在 `line`
- 无 GPU 时 render 停在 queued
- Ken Burns 仍进不了 `06-export/`
- 审片必须有声有字

## 默认选择

- 分镜表本地做，不依赖剪映账号
- 出图优先 Imagine API，否则任务单 + 手传
- 视频模型是 H3，但是按镜、按合同，不是小说进成片出
- 003 第 01 集仍是唯一验收片；02–05 集只读剧本，不铺生产
