> 长期规则。云端 agent 每次开工前读一遍，不是一次性任务单。
> 一次性改造步骤见 `CLOUD-REBUILD-TASKS.md`。本集诊断见 `DIAGNOSIS-ep01.md`。

# 云端短剧生产流程规则

目标形态：**云端独立跑完 80 集，本地只做抽检。**

这一条决定了本文件的全部设计。80 集 × 8–10 镜 ≈ 700 镜，人工逐镜过关卡在这个量级上不可能。
所以每一条导演层规则都必须**能被机器执行** —— 写在文档里但机器查不到的规则，等于不存在。

判断一条规则该不该进本文件：**它能不能被 `validate_shots.py` 检出来？**
不能的，要么改成能检的，要么明确标为「人工抽检项」。

---

## 一、单位是一场戏，不是一张图

旧 AI 短剧的做法是「先画图、再各自生成 6 秒、再 concat」。它产出的必然是拼接片，因为
每一镜都是模型对场景的一次独立想象 —— 灯光、机位高度、墙面、衣服褶皱全部会漂。

导演的做法是：**一场戏 = 一个舞台 + 若干机位。** 镜头是这个舞台上的覆盖，不是十张独立海报。

由此推出三条不可让的底线：

1. **先有舞台，才准写镜头。** 没有该场的 `sets` 条目和 `blocking`，这一场的镜头一律不准写。
2. **同一场的镜头必须在同一条轴上。** 禁止一人一张摆拍。
3. **换场才硬切。** 场内靠末帧续，跨场从新场 blocking 重新起。

---

## 二、关卡

不通过不进下一关。改了某关，只重做该关及下游；已锁定的主图不换。

```
剧本
  │
  ▼
Gate A  锁剧本 + 画风/画幅确认 + 蓝图（按场换装、时间线）
  │
  ▼
Gate B  锁资产：每角色 face + master；双人戏有身高图；每场空镜 master
  │
  ▼
Gate S  锁舞台：sets.json（轴 + 光位 + 站位）+ 每场 blocking
  │
  ▼
Gate C1 锁覆盖：一场至少 master + 一个更紧的机位；每镜一件新信息
  │
  ▼
Gate C2 锁分镜合同：shots.json 过 validate_shots.py（零 ERROR）
  │
  ▼
Gate D  首帧：场首镜从 blocking 改；场内续镜从上一镜改
  │
  ▼
Gate E  出片：continue + 人物有交集 → I2V 吃末帧；否则用设计首帧
  │
  ▼
Gate E+ 审剧情：旁白 + 字幕的审片轨。无声切只能审脸，不能审剧情
  │
  ▼
Gate F  成片：高棉语本地轨 / 中文导出轨
```

**Gate C2 是唯一的机器闸门。** 它不过，后面全部不准跑 —— 这是 80 集无人守的前提。

---

## 三、分镜合同 schema

`shots.json` 是**唯一真源**。所有 markdown 视图必须由它生成，不能反过来。

`video_prompt` 必须在 JSON 里。结构和指令分家等于没有校验：运镜与声明不一致、
环绕泄漏、台词泄漏这三类问题，只有在同一个文件里才查得出来。

### 每镜必填

| 字段 | 取值 | 说明 |
|---|---|---|
| `id` | `SH001` | |
| `scene` | sets 注册表的 id | 没有它就没有轴线校验 |
| `seconds` | 1–15 整数 | >6 必须给 `segments` |
| `setup` | `master` / `close` / `ots` / `insert` / `single` | **枚举，不是自由文本** |
| `scale` | `wide` / `full` / `med` / `close` / `insert` | |
| `move` | `static` / `push` / `pull` / `pan` / `track` | **一镜一个运动**，不许复合 |
| `axis` | `left` / `right` / `center` | 机位在 180 度线哪一侧，**不是镜头微偏** |
| `lens` | `35mm` / `50mm` / `85mm` | |
| `facing` | `camera`/`down`/`left`/`right`/`away`/`scene` | |
| `cut` | `continue` / `hard` | 硬切只用于换场 |
| `from` | 父镜 id，硬切为 `null` | |
| `derived_from` | `<scene>.blocking` 或父镜 id | 首帧从哪张改 |
| `first_frame_source` | `blocking` / `designed_frame` / `last_frame` | **把末帧决策显式化，可审计** |
| `characters` | slug 数组 | 缺它无法判末帧续、无法挂参考图 |
| `enters` | slug 数组，可选 | 本镜过程中**入画**的人；首帧不需要有他们。见第四节 |
| `new_info` | 一句话 | 这几秒观众新知道的**一件**事 |
| `line` / `line_kind` / `caption` | `narration`/`dialogue`/`sms` | 对白**只能**待在这里 |
| `camera` | 一句运镜 | 措辞须与 `move` 一致 |
| `action` | 这几秒身体做的一件事 | 不准含台词 |
| `look` | **光位 / 景深 / 站位** | 物理连续性，**不是情绪形容词** |
| `video_prompt` | ≥80 字符 | 给模型的说明书，不含对白 |
| `negatives` | 见下 | |

### `look` 写什么

这一格最容易写坏。它是**能对着 blocking 检查的物理描述**：

- ✅ `头顶荧光冷白从上打，缝纫机工作灯暖黄从下打，车缝排在右`
- ❌ `oppressive busy atmosphere`、`dignity strength`

情绪不属于这里 —— 新信息在 `new_info`，情绪由表演和景别承担。
光位不锁死，相邻镜必然变色温，而观众说不出哪里怪，只觉得假。

**光位锁在场上**：`sets.json` 每场一个 `light` 字段，本场每镜的 `look` 复述它。

### `negatives` 必须覆盖五类

缺一类就是给模型留了默认行为的口子：

```
no orbit, no crash zoom, no face drift, no clothing change,
no subtitles, no captions, no burned-in text, no watermark, no lip-sync speech
```

视频模型把 "cinematic" 默认理解成**缓慢环绕**。不显式禁止，每镜都会绕。

---

## 四、末帧续的判据（最容易搞错的一条）

`cut: continue` **不等于**一定吃末帧。

判据不是「有没有交集」，而是：**本镜首帧需要的人，父镜末帧里有没有。**

```
needed  = characters - enters      # enters 里的人在本镜过程中入画，首帧不需要有
missing = needed - 父镜.characters

missing 非空  →  禁止 last_frame，必须 designed_frame
missing 为空  →  应当 last_frame（用 designed_frame 会掉连续性，只是 WARN）
换场          →  blocking
```

**为什么不能用「交集非空」判断：** 交集非空但缺了某个人，那个人照样会被凭空造出来。
父镜是 `[sophea]`、本镜是 `[sophea, piseth]`，交集非空，但皮萨不在父镜末帧里 ——
如果他不是入画而是本该已在画中，吃末帧就会得到一张编造的皮萨脸。

**`enters` 字段**：本镜过程中走进画面的人写在这里。
比如 12 秒的 master：索菲娅在缝纫，皮萨从过道深处走进来 ——
`characters: ["sophea","piseth"]`、`enters: ["piseth"]`，首帧只需要索菲娅，可以吃末帧。
不写 `enters`，校验器会以为皮萨首帧就该在画里而拦下来。

**同样致命的反向错误：父镜没有人。** 从一张空景的末帧续出人物，
和从错的脸续一样是凭空造。所以开场镜不许是空景 —— 它会连带毁掉第二镜。

无论哪种情况，`cut` 都仍写 `continue`（因为地理和光位连续），变的只是 `first_frame_source`。

---

## 五、镜头节奏

### 单集规格（已锁定）

**60–75 秒 / 8–10 镜。** 80 集一致，不许逐集浮动。校验器超范围直接 ERROR。

太短装不下「一场冲突 + 一个钩子」的完整节拍；太长对竖屏留存不友好，且 80 集成本翻倍。

### 运镜配比

| 规则 | 上限 / 下限 |
|---|---|
| `push` 占比 | **≤ 40%** |
| 每场至少一个真正 `static` | 必须 |
| 全集至少一个 `pull` 或一个 ≥8 秒长镜 | 必须 |

整集一直在慢推 = 没有节奏对比，这是继环绕之后**第二明显的 AI 味**。
禁了 orbit 却把 push 写进每一镜，等于换了个姿势露出破绽。

### 少切、长镜、镜内调度

**每一刀都是一次让模型重新想象场景的机会。** 切得越碎，漂移越多。

优先用更少、更长的镜头，把变化放进画框内部靠走位完成。
镜长要长短交错，不要机械均分。

### 超过 6 秒怎么办

画布单 clip 上限 6 秒。**不许为了迁就这个上限把长镜切碎。**

拆成同轴续段：

```
SH003（12s，master，pull，35mm，axis=center）
  ├─ SH003a  6s  首帧 = SH002 末帧    动作前半
  └─ SH003b  6s  首帧 = SH003a 末帧   动作后半
```

- `lens` / `axis` / `setup` / `move` / `look` **完全一致，一个字不改**
- 只有 `action` 描述动作推进到哪一阶段
- 拼接不加转场

**拆的是生成单元，不是剪辑点。** 成片上这是一个 12 秒长镜。
这叫隐形接点，和拼接感正好相反 —— 拼接感来自机位跳变，不来自帧的连续。

反过来：**≤6 秒的镜头不许拆。** 6 秒拆两段只是白多一个接点、多一次漂移机会。

---

## 六、声音

R12：**AI 生成的音频永远不当声音轨。** 环境声、动作音效、BGM 一律后期叠。

画布 clip **一定带音频**，而 `ffmpeg concat -c copy` 会把它原样烧进成片。
各 clip 底噪不一致本身就是廉价拼接感的主要来源。

处理方式是**换成同长静音轨，不是删音轨**：

```bash
ffmpeg -y -i in.mp4 -f lavfi -i anullsrc=r=48000:cl=stereo \
  -map 0:v -map 1:a -c:v copy -c:a aac -b:a 128k -shortest out.mp4
```

删掉音轨会让审片轨报错（它要把 `[0:a]` 压低当背景床），统一的流布局也让 `-c copy` 拼接不会崩。

成片阶段要铺的：

- **环境底噪贯穿整场不断**（缝纫机声在切镜头时绝对不能断）
- 动作音效
- **声音早于画面进入**（L-cut / J-cut）

BGM 用高棉流行 / 婚礼锣鼓 / pinpeat，不要二胡古风。

---

## 七、转场与剪辑

- **只用硬切。** 禁止 fade / dissolve / 任何转场效果 —— 竖屏短剧用叠化是明显的业余信号。
- 升级项是 **cut on action**：生成时让动作跨过剪辑点，剪辑时两头各修几帧。
- 不要用画布自带的 stitch（它加转场、压分辨率、剪辑点固定在 clip 边界）。单镜下载后自己拼。

---

## 八、一致性与本地化

- **人名不译，用高棉 slug，全流程唯一。** `sophea`、`sara`、`piseth`、`ros`、`malis`、`davi`、`nita`。
  禁止 `Sofia` / `Pissa` / `Rose` 这类英化写法，也禁止中文音译进字幕。资产 key 就是 slug。
- 每个角色、每个主场景**全剧只许一次全新生图**得到 `master`。换装、日夜、湿身全部从它改。
- 双人戏必须先有身高图，相对身高写进角色卡。模型不会自己记住谁高。
- 招牌能看清就必须高棉文为主；画面里不准出现生成的字幕或标题。
- 钱和软件用金边的：美元 + 瑞尔、ABA/Wing、Facebook/Telegram。
- 佛、僧、王室、吴哥可以出镜，必须庄重，不当搞笑或魔法道具。

---

## 九、资产注册表

`assets.json` 是角色、场景、道具的唯一索引，key 一律用高棉 slug。

| 段 | 每项要有 | 为什么 |
|---|---|---|
| `characters.<slug>` | `root_face` **和** `root_full`（两张不同的图） | 近景要紧脸裁切，全身要管服装身形；一张顶两用两头都弱 |
| `characters.<slug>` | `age`、`notes`（装、发型、标志物） | 80 集换装要从 master 改，不是重新生成 |
| `scenes.<slug>` | `master` **和** `blocking` | 没有 blocking 不准写该场镜头，首帧也无处派生 |
| `scale` | 每组常同框组合一张身高图 | 模型不会自己记住谁高 |
| `props` | 全剧复现道具 | **银铃是贯穿 80 集的身份信物**（第 12 集要两半合上、断口严丝合缝），不锁资产做不到 |

键名必须统一。有的角色写 `root_face`、有的写 `root`，「脸优先挂参考图」这一步就无法自动化。

## 十、开工前

```bash
python3 validate_shots.py \
  --sets sets.json --shots epNN_shots.json --assets assets.json --warn-as-error
```

带 `--assets` 会做分镜↔资产交叉校验：引用了不存在的角色或场景、场景缺 blocking、
近景角色没有脸图、缺身高图、缺道具，全部在开工前报出来。

**这一层对 80 集尤其要紧**：分镜引用一个不存在的资产时，脚本不会报错，
模型会默默凭空造一个人或一个空间，等成片出来才发现。

零 ERROR 才准进 Gate D。参考样例：`gold/Episode1_shots.gold.json`（8 镜 64 秒，零 ERROR 零 WARN）。

金标准能过，说明这套规则可满足。如果你的分镜过不了，是分镜的问题，不是规则太严。
