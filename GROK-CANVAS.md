# Gate D/E 走 Grok Imagine 画布（手动）

`VIDEO.md` 是 API 路线（Hailuo / H3 / CompShare，`render_shots.py` 自动吃末帧）。  
本文件是**手动路线**：在 grok.com/imagine 的画布上出图出片，回流到同一套 `productions/<slug>/` 目录。

导演层规则不变。`XIAOYUNQUE.md` 硬规则 1–6、`QUALITY.md` R8/R9/R10 一条都不放。  
换的只是执行工具，不是流程。

---

## 一、先关掉 Agent 自动规划

画布有两种用法，只有一种能用。

| 用法 | 结果 |
|---|---|
| 丢一句 brief，让 Agent 自动拆 6–12 个 panel 再 stitch | **就是你不满意的那种拼接片。禁止。** |
| 把画布当手动节点图，一镜一个节点，父子关系自己连 | 可用 |

Agent 的自动 panel 规划没有舞台、没有轴线、没有末帧续，每个 panel 都是独立文生图。  
它复现的正是 `~/WorkBuddy/` 那份 810 镜提示词的失败模式。

**画布上唯一的输入来源是 `shots.json`。** 没过 `check_storyboard.py` 不准开画布。

---

## 二、画布的硬约束，以及怎么绕

| 约束 | 画布现状 | 本工程要求 | 处理 |
|---|---|---|---|
| 单 clip 时长 | ≤ 6 秒 | `shots.json` 有 8 / 10 / 12 秒 | **拆同轴续段**，见第三节 |
| 分辨率 | 720p | 9:16 → 720×1280 | 够 FB/TikTok。成片不放大 |
| 参考图数量 | 编辑节点最多 3 张 | `still_refs()` 会给到 6 张 | 按优先级取前 3，见第四节 |
| stitch 功能 | 自动加转场 | 需要 cut on action | **不用 stitch。**单镜下载回 `05-shots/` |
| clip 自带音频 | 有 | R12：环境声 BGM 后期叠 | 一律当无声素材用 |
| 首帧锁定 | `image-to-video` 锁首帧；`reference-to-video` **不锁** | R10 末帧续要求首帧就是上一镜末帧 | 续镜**必须**用 image-to-video |

最后一行是最容易踩的。参考图模式看起来更方便（能同时塞脸和场景），但它不锁首帧，
末帧续会失效，接点立刻露出来。**只要 `cut=continue`，就走 image-to-video。**

---

## 三、超过 6 秒的镜头怎么拆

`coverage.md` 里 SH003 是 12 秒的 master：赶工 + 皮萨从车间深处走进画面，
两件事在同一个镜头内靠走位完成。这一镜是整集最像导演的地方，**不许为了迁就 6 秒把它切碎**。

拆成两段生成，成片上仍是一个镜头：

```
SH003（12s，master，static，50mm，axis=center）
  ├─ SH003a  6s  首帧 = SH002-last.jpg      动作前半：赶工，皮萨还没进画
  └─ SH003b  6s  首帧 = SH003a 末帧          动作后半：皮萨从深处走到近端
```

两段之间：

- `lens` / `axis` / `setup` / `move` / `look` **完全一致**，一个字都不改
- 只有 `action` 描述动作推进到哪一阶段
- 拼接时直接 concat，不加转场

**拆的是生成单元，不是剪辑点。** 观众看到的是一个 12 秒长镜。
这叫隐形接点，和"拼接感"正好相反 —— 拼接感来自机位跳变，不来自帧的连续。

`grok_tasks.py` 会自动按 6 秒上限拆段并算好每段首帧来源。

---

## 四、每一镜在画布上做什么

先出任务单：

```bash
python3 scripts/grok_tasks.py --prod productions/004-yuye-jinlian --only SH003
```

任务单会直接给出：父图路径、参考图（已按优先级裁到 3 张）、模式、要粘贴的提示词、回流文件名。
下面是它背后的规则。

### 4.1 首帧从哪来（Gate D）

和 `STORYBOARD.md` 的表一致，画布上的对应操作：

| 时机 | 父图 | 画布操作 |
|---|---|---|
| 一场的第一镜 | 该场 `blocking.jpg` | 拖入父图 → Edit 节点 → 粘贴 still 提示词 |
| 场内续、还没有视频 | 上一镜 `04-frames/SH00N.jpg` | 同上，父图换成上一镜首帧 |
| 场内续、已有 `{from}-last.jpg` | — | **不出首帧**，直接进 4.3 |
| 换场硬切 | 新场 `blocking.jpg` | 同第一行 |

**禁止对同一场另开一张文生图摆拍。** 父图为空的 Edit 节点等于文生图。

### 4.2 参考图取哪 3 张

`still_refs()` 按这个顺序给，画布上取前 3：

1. 出场角色的 `sheet.jpg` / `face.jpg`（**脸优先，一人一张**）
2. 该场 `blocking.jpg`（地理）
3. 该场 `master.jpg`（光位）

两个人的戏就是 `face×2 + blocking×1`，场景光位靠父图本身带住。
一个人的戏是 `face×1 + blocking×1 + master×1`。

R9：双人戏必须已有 `scale-*.jpg`，相对身高写进角色卡。画布不会自己记住谁高。

### 4.3 出片（Gate E）

| `cut` / 人物关系 | 首帧 | 画布模式 |
|---|---|---|
| `continue`，且与上一镜**同机位、人物有交集** | 上一镜真末帧 | 同场续再 FL2VA（锁首帧） |
| `continue`，但换机位或切到**另一个人** | 本镜设计首帧 | 首帧图生（FL2VA） |
| `hard`（换场） | 新场设计首帧 | 首帧图生（FL2VA） |
| 有设计 `end_frame`（不是 `-last.jpg`） | 首帧 + 设计尾帧 | 首尾帧 |
| 有 `sheet.jpg` / `face.jpg` | 仍锁首帧 | 参考图外挂锁脸，不替代第 0 秒 |

第二行是 `render_shots.py` 的既有逻辑，容易漏：**同场 `continue` 不等于一定吃末帧。**
如果这一刀是从萨拉切到皮萨，两人不同框，吃上一镜末帧只会得到一张错的脸。
这种情况用本镜锁定的设计首帧，`cut` 仍然写 `continue`（因为地理连续）。

提示词一律用 `grok_tasks.py` 编译出来的那一段，不要手写。它已经含：

- `No spoken dialogue. No lip-sync. Burned-in captions are forbidden.`
- `lens, setup, move` 头
- `camera` / `action` / `look`
- `video_prompt` 正文
- `Avoid: {negatives}`

### 4.4 末帧

画布上出片后用「提取末帧」，或者下载 mp4 之后由 `ingest_shots.py` 本地提（和 API 路线同一条 ffmpeg 命令，
`-sseof -0.05`，取倒数第二帧附近，避免最后一帧的压缩糊）。

---

## 五、回流

画布产物用镜号命名，丢进 inbox：

```
productions/<slug>/.director/inbox/
    SH001.jpg          # 首帧 → 现有 scan_inbox 走候选，人锁定后进 04-frames/
    SH003a.mp4         # 拆段
    SH003b.mp4
    SH004.mp4
```

首帧走已有的图片通道（`STUDIO.md` 第 42 行起）：扫 inbox → 进候选 → 人锁定 → 写 `04-frames/`。
**候选不自动覆盖正式文件**，这个卡点保留。

视频走新加的通道（`scan_inbox()` 只收静帧，视频原先没有门）：

```bash
python3 scripts/ingest_shots.py --prod productions/004-yuye-jinlian --dry-run
python3 scripts/ingest_shots.py --prod productions/004-yuye-jinlian
```

它会：合并同镜拆段 → 写 `05-shots/SH00N.mp4` → 提 `04-frames/SH00N-last.jpg`
→ 对不上 `shots.json` 的文件不动 → 报告哪些镜还缺 → 提示下一镜该不该吃这张末帧。

**它还会把模型音频换成静音轨。** 这一步是必须的：Hailuo Fast 默认无声，但**画布 clip 一定带音频**，
而 `assemble.sh` 和 `mix_review_track.py` 都是 `-c copy` 拼接 —— 不换掉，AI 生成的人声和底噪会一路
烧进成片（违反 R12），而且各 clip 底噪不一致正好就是"廉价拼接感"的主要来源。

换成静音轨而不是直接删音轨，是因为 `mix_review_track.py` 会把 `[0:a]` 压到 0.18 当背景床，
删掉音轨它会报错；统一的流布局也让 `-c copy` 拼接不会崩。排查画布输出时可以 `--keep-audio` 临时保留。

然后照旧：

```bash
python3 scripts/mix_review_track.py --prod productions/004-yuye-jinlian   # Gate E+ 审剧情
bash scripts/assemble.sh productions/004-yuye-jinlian                     # 成片
```

---

## 六、禁止清单

画布上最容易把片子做回"AI 味"的六件事：

1. **用 Agent 一句话自动拆 panel。** 见第一节。
2. **用画布的 stitch 出成片。** 它加转场、压 720p、且剪辑点在 clip 边界上 —— 正好是你要避开的一顿一顿。
3. **让它环绕。** `negatives` 里 `no orbit, no crash zoom` 必须带上。视频模型把 "cinematic" 默认理解成缓慢环绕，不禁止就每镜都绕。`check_storyboard.py` 的 `ORBIT_TERMS` 已经在源头拦了，画布上别手改回去。
4. **让它烧字幕。** 提示词已含 `Burned-in captions are forbidden`。招牌能看清就必须高棉文为主（R8），字幕后期叠。
5. **用 clip 自带的人声当配音。** R12。一律无声素材。
6. **续镜用 reference-to-video。** 不锁首帧，末帧续失效。见第二节最后一行。

---

## 七、开工前检查

```bash
python3 scripts/check_prod.py --prod productions/004-yuye-jinlian
```

不过关不开画布。要看的是：

- [ ] `sets.json` + 每场 `blocking.jpg` 齐（Gate S）
- [ ] `coverage.md` 一场有 master + 更紧的机位（Gate C1）
- [ ] `shots.json` 过 `check_storyboard.py`：`setup` / `move` / `derived_from` / `lens` / `axis` / `camera` / `action` / `look` / `video_prompt` / `negatives` 全有
- [ ] 出场角色 `face.jpg` 齐；双人戏有 `scale-*.jpg`（R9）
- [ ] 每镜 `negatives` 含 `no orbit, no crash zoom, no face drift, no clothing change`
