# 诊断 · 云端生产流程（雨夜金莲 第1集）

对象：`incoming/Episode1_shots.cloud.json` + `CURRENT_PRODUCTION_PIPELINE.md`  
方法：先独立诊断，再对照本地标准列差距。结论全部可由 `validate_shots.py` 复现。

```bash
python3 validate_shots.py --shots incoming/Episode1_shots.cloud.json
# 镜头 10 个，总长 49s / ERROR 225 条 / WARN 2 条
```

对照组（同一集，本地导演设计，同一把尺子）：

```bash
python3 validate_shots.py --sets gold/sets.json --shots gold/Episode1_shots.gold.json --warn-as-error
# 镜头 8 个，总长 64s / ERROR 0 条 / WARN 0 条
```

金标准能过，说明这套规则是可满足的，不是刁难。

---

## 先说最重要的一件事：自我诊断第 1 条方向搞反了

原文：

> **末帧续不够严格**：很多镜头仍用 reference-to-image / 独立生成，而不是严格从上一镜 last frame 做 image-to-video。

隐含的结论是"要更严格地执行末帧续"。**这个方向是错的，照它改会让画面更坏。**

真正的问题是**镜头图把 `cut: continue` 标在了不该标的地方**。全集 10 镜，9 镜标 `continue`，形成一条从 SH001 一路串到 SH010 的直线。但其中至少三处根本不具备续接条件：

| 镜 | 从 | 问题 |
|---|---|---|
| SH004（索菲娅首次出现） | SH003（校服单据 insert） | SH003 画面里没有索菲娅 |
| SH007（皮萨） | SH006（索菲娅独自缝纫） | 两镜无共同人物 |
| SH009（罗丝，走廊） | SH008（索菲娅，车间） | 无共同人物，且**换了空间** |

于是两条路都是死的：

- **严格执行末帧续** → 模型拿到一张不含目标角色的末帧，只能凭空造脸 → 这就是角色漂移的来源
- **不执行、改回独立生成** → 回到"每镜重新想象" → 这就是拼接感的来源

所以要修的是**图**，不是执行力度。本地 `render_shots.py` 早就有这条判据：同场 `continue` 且**与父镜有共同人物**才吃末帧；覆盖切到另一个人时用本镜锁定的设计首帧，`cut` 仍写 `continue`（因为地理连续），但首帧不能用末帧。

---

## P0 结构性缺陷

会直接产生你感觉到的拼接感和角色漂移。

### D1 换场没有硬切

SH009 是罗丝在**厂房走廊**隔玻璃看车间，和 SH001–SH008 的**车间过道**是两个空间、两条轴。本地把它们注册成 `factory-floor` 和 `factory-office` 两场，并明确写了「硬切进场」。

云端把它写成 `cut: continue` / `derived_from: SH008`。让模型从索菲娅的面部末帧续出"罗丝在走廊隔雨玻璃看车间"，物理上不可能连续。

旁证：SH009 的 negatives 里有 `not outdoor together` 和 `clear glass rain streaks`。这两条是在**事后补漏** —— 说明已经生成出过"两人在同一个开放空间/淋同一场雨"的错图。根因不在提示词，在图结构：跨场必须硬切，首帧从新场的 blocking 改。

### D2 没有「场」的概念，Gate S 整层缺失

`setup` 被当自由文本用：`"factory interior wide"`、`"Sara workstation"`、`"Rose through glass"`。这把两件不同的事塞进了一个字段 —— **哪一场**（空间）和**什么机位**（覆盖）。

后果是连锁的：没有场 → 没有轴线 → 没有 blocking → 首帧无处派生 → 只能文生图或硬串末帧。他们自我诊断第 8 条写了"无 blocking.jpg / master light 系统"，但没意识到这是 D1 和 D2 的**根因**，而不是一条独立的待办。

### D3 `axis` 填的不是轴线

`"slight left"`（SH004）、`"slight right"`（SH007）是镜头微偏，不是轴线。轴线指**机位在 180 度线的哪一侧**，只有 left / right / center 三个值。

更要紧的是对峙戏：SH007（皮萨）标 `slight right`，SH008（索菲娅回应他）标 `center`。正反打必须让两人稳定分居轴的两侧，否则观众下意识觉得"不对"。现在这组是糊的。

---

## P1 质感缺陷

决定"像不像导演拍的"。

### D4 六成镜头在慢推，零拉镜

这一条被自由文本掩盖了，把 `move` 按语义归一到枚举后才露出来：

| move | 镜数 |
|---|---|
| push | 6 |
| static | 2 |
| pan | 1 |
| track | 1 |
| **pull** | **0** |

```
6/10 镜是 push（60%），超过上限 40%
全集既没有拉镜，也没有 ≥8s 的长镜；观众没有一次换气的地方
```

他们在 negatives 里禁了 `orbit` 和 `crash zoom`，这是对的。但**把 push 写进了几乎每一镜** —— 环绕之后第二明显的 AI 味就是"镜头永远在缓慢前进"。没有固定长镜、没有拉开，就没有节奏对比。

对照金标准：`static×4、push×3、pull×1`。其中 SH003 是**拉镜**：从两人的近景拉回车间全貌，同时皮萨从过道深处走进来。一个动作既完成了呼吸，又完成了新人物入场。

### D5 `look` 被当成情绪形容词，光位完全没锁

全集十镜的 `look`：`oppressive busy atmosphere`、`heartbreaking helplessness`、`pressure of workload`、`decision and kindness`、`warm firm`、`focus resilience`、`conflict`、`dignity strength`、`restrained shock fate`、`strong hook`。

**没有一个字描述光。**

本地 schema 里 `look` 是物理连续性 —— 光线、背景虚实、站位，必须能对上 blocking。情绪不属于这里（新信息在 `new_info`，情绪由表演和景别承担）。

光位不锁在场上，相邻镜必然变色温。这正是 `~/WorkBuddy/` 那版分镜的老毛病：S1-01 是 `harsh white fluorescent`，同一场戏往后六镜的 S1-06 变成 `warm lamp light`，同一分钟内换了光。这是"AI 味"的三大来源之一，而且观众说不出哪里怪，只觉得假。

金标准把光位写进了 `sets.json` 的 `light` 字段（车间：头顶荧光冷白从上 + 机器工作灯暖黄从下；走廊：钠灯从上 + 车间荧光从右侧玻璃透进来），本场每一镜的 `look` 都复述它。

### D6 镜长机械均分，且从不做镜内调度

时长序列：`4,5,3,4,5,6,6,6,6,4`，平均 4.9 秒，10 刀 49 秒。**没有一镜超过 6 秒**，所以拆段机制实际从未启用 —— 也就是说从来没有"一镜之内靠走位完成两件事"。

在 AI 制作里这一点被严重低估：**每一刀都是一次让模型重新想象场景的机会。** 切得越碎，漂移越多。导演的做法相反 —— 用更少、更长的镜头，把变化放进画框内部。

对照金标准 SH003：12 秒的 master，赶工和皮萨从深处走来在同一个镜头里靠走位完成。因为超过 6 秒，它拆成 `SH003a`/`SH003b` 两段生成，但 `lens`/`axis`/`setup`/`move`/`look` 一字不改，末帧续接，拼接时不加转场 —— **成片上是一个 12 秒长镜，不是两刀。**

### D7 `split` 用错了

`SH006` 和 `SH009` 都标了 `split: "optional 006a+006b"`，但两镜都是**正好 6 秒**。

拆段的唯一目的是绕开画布 6 秒上限。6 秒拆成两段，只是白多一个接点、多一次漂移机会，没有任何收益。反过来，真正需要拆的（>6 秒的长镜）一个都没有，因为没有长镜。

---

## P2 流程完整性缺陷

决定能不能无人守跑完 80 集。这一层最关键，因为你的目标是云端独立生产、本地只抽检。

### D8 校验的东西不是发给模型的东西

`Episode1_shots.json` 里**没有 `video_prompt`** —— 它在第三份 196 行的 MD 里。

结构和指令分家，等于没有校验。以下三类问题在当前架构下**原理上无法自动发现**：

- 运镜措辞与声明的 `move` 不一致（声明 static，提示词里写 push）
- `orbit` / `crash zoom` 从提示词泄漏进去
- 台词泄漏进提示词

JSON 必须是唯一真源，`video_prompt` 必须在里面。MD 可以由 JSON 生成，不能反过来。

### D9 没有 line / caption / line_kind，且台词泄漏进了 action

云端 JSON 完全没有对白字段。后果：

- 出不了审剧情切（本地 `mix_review_track.py` 直接报 `shots have no line fields`）
- 做不了高棉语本地轨 / 中文导出轨（R1、R2）

而台词跑到了别处 —— SH005 的 `action` 是 `"Sofia says go to hospital I will finish for you"`，同一镜的 negatives 又写 `no lip-sync`。**一边叫模型说话，一边禁止口型，自相矛盾。** 模型的实际行为不可预测，通常是嘴动但对不上。

对白只能待在 `line` / `caption`，字幕后期叠。

### D10 没有 characters 数组

根资产在 MD 里列了 UUID，但没有绑定到每一镜。后果：

- 无法自动挂参考图（脸优先、上限 3 张这条规则没有执行依据）
- **无法计算人物交集**，也就无法判断 D2 那条末帧续判据
- 无法系统性抽检脸漂移

他们自我诊断第 6 条"参考图优先级执行不彻底"，根因就在这里 —— 没有 `characters`，参考图只能靠人记。

### D11 人名三套并存

| 来源 | 写法 |
|---|---|
| 流程文档 | 索菲娅、萨拉、皮萨、罗丝 |
| shots.json | Sofia、Sara、Pissa、Rose |
| 本地锁定资产 | `sophea`、`sara`、`piseth`、`ros` |

R2 要求人名不译，用高棉拼写。注意 `Pissa` 和 `piseth` 是两个不同的转写，`Sofia` 和 `sophea` 也是。80 集下来资产一定对不上。**资产 key 必须用高棉 slug，且全流程唯一。**

### D12 音频（他们已自查，方案要补一层）

自我诊断第 9 条对了：clip 自带音频没剥离。补充两点他们没提到的：

- **画布 clip 一定带音频**（不像 Hailuo Fast 默认无声），而 `ffmpeg concat -c copy` 会把 AI 人声和底噪原样烧进成片，违反 R12
- 各 clip 底噪不一致，本身就是"廉价拼接感"的主要来源之一

正确做法不是删音轨，而是**换成同长静音轨**：审片轨要把 `[0:a]` 压低当背景床，删掉会报错；统一的流布局也让 `-c copy` 拼接不会崩。本地 `scripts/ingest_shots.py` 已实现（实测 -91 dB）。

### D13 末帧取帧位置

云端 `-sseof -0.1`，本地 `-sseof -0.05`。取的帧离真正末帧更远，续接精度略低。小事，但既然目标是两边产物互通，建议对齐到 `-0.05`。

### D14 转场

"之前测试过 fade/dissolve" —— 竖屏短剧用叠化是明显的业余信号。他们已经落到 hard cut，方向对了，但应该**写成硬规则锁死**，并把真正的升级项写清楚：cut on action（生成时让动作跨过剪辑点，剪辑时两头各修几帧），而不是在接缝上加效果。

---

## 与本地标准的差距总表

| 本地 | 云端现状 | 差距 |
|---|---|---|
| Gate S：`sets.json` + 每场 `blocking.jpg`；没舞台不准写镜头 | 无 | **整层缺失**（D2） |
| Gate C1：`coverage.md` 一场至少 master + 更紧机位 | 无覆盖概念 | 缺失 |
| Gate C2：`shots.json` 过 `check_storyboard.py` | markdown + 无校验 | **缺失**（D8） |
| `scene` 引用 sets 注册表 | 无此字段 | 缺失 |
| `setup` ∈ master/close/ots/insert/single | 自由文本 | 类型错误 |
| `move` ∈ static/push/pull/pan/track，一镜一个 | 复合自由文本 | 类型错误（掩盖了 D4） |
| `axis` ∈ left/right/center | `slight left` 等 | 语义错误（D3） |
| `look` = 光位/景深/站位 | 情绪形容词 | **语义错误**（D5） |
| `new_info` 每镜一件新信息 | 无 | 缺失 |
| `line`/`caption`/`line_kind` 每镜必有 | 无，且泄漏进 action | **缺失 + 矛盾**（D9） |
| `characters` 数组 | 无 | 缺失（D10） |
| 换场硬切，首帧从新场 blocking | 全程 continue 直线 | **结构错误**（D1） |
| continue 且人物有交集才吃末帧 | 无判据 | **结构错误**（D2 开头） |
| 一镜 6 秒优先，长镜拆同轴续段 | 全部 ≤6s，从不镜内调度 | 质感差距（D6/D7） |
| 已锁定 8–10 镜 / 60–75 秒 | 10 镜 / 49 秒 | 低于下限（D15） |
| R2 人名不译，高棉 slug | 三套并存 | 一致性风险（D11） |
| R12 音频后期叠 | 未剥离 | 已自查（D12） |
| Gate E+ 审剧情（旁白+字幕） | 无 | 缺失（D9 的下游） |
| Gate F 双轨成片（高棉/中文） | 无 | 缺失 |

---

## D15 单集时长超出锁定规格

之前三个来源不一致：剧本制作提示写 90–120 秒，本地 `PIPELINE.md` 写 50–75 秒，
云端 ep01 实际 49 秒。

**已定案：60–75 秒 / 8–10 镜，80 集一致。**（2026-08-24）

云端 ep01 的 49 秒低于下限，判 ERROR。它装不下「一场冲突 + 一个钩子」的完整节拍 ——
当前为了塞进 49 秒，5 个节拍被压成平均 4.9 秒一刀，这正是 D6 那条碎切的直接后果。
另一头 90–120 秒对竖屏留存不友好，且 80 集生成成本翻倍。

已写进校验器（`EPISODE_SECONDS = (60, 75)`、`EPISODE_SHOTS = (8, 10)`）。
金标准是 8 镜 64 秒，落在区间内。
