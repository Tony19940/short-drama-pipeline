> 一次性改造任务单。做完就归档。长期约束读 `CLOUD-PIPELINE.md`。
> 每项都有验收标准；**没跑过验收命令不算完成。**

# 云端流程改造任务单

目标形态：云端独立跑完 80 集，本地只抽检。  
当前状态：`Episode1_shots.cloud.json` 跑 `validate_shots.py` 是 **225 ERROR / 2 WARN**。

顺序有依赖，**不要跳着做**。T1 不做完，T5 以后全是白工。

```bash
# 每完成一项都跑这个
python3 validate_shots.py --sets sets.json --shots ep01_shots.json --warn-as-error
```

---

## T0 · 先读三份东西（30 分钟，不产出文件）

1. `DIAGNOSIS-ep01.md` —— 尤其是开头「自我诊断第 1 条方向搞反了」那一节
2. `CLOUD-PIPELINE.md` 第四节「末帧续的判据」
3. `gold/Episode1_shots.gold.json` —— 逐字读一遍，这是唯一的目标形态样例

**特别注意：不要按自己那份自我诊断的第 1 条去改。**
「更严格地执行末帧续」这个方向是错的 —— 问题在镜头图把 `continue` 标错了地方，
照原方向改会让模型从不含目标角色的末帧凭空造脸，角色漂移会更严重。

---

## P0 · 结构（不做完，后面全是白工）

### T1 · 建 sets 注册表，补 Gate S

**做什么**

1. 把第 1 集拆成两场：`factory-floor`（车间过道）、`factory-office`（走廊隔玻璃）
2. 每场写 `sets.json` 条目：`id` / `master` / `blocking` / `axis` / `light` / `marks`
3. 每场生成 `blocking.jpg`（空镜 + 站位标记）
4. `light` 字段是这一场的光位锁，本场每镜 `look` 都要复述它

抄 `gold/sets.json`，它已经把这两场写好了。

**为什么是第一件事**

没有场就没有轴线、没有 blocking、首帧无处派生，只能文生图或硬串末帧。
你自我诊断的第 8 条（无 blocking / master light 系统）不是一条独立待办，
它是 D1（换场没硬切）和 D2（没有场概念）的**根因**。

**验收**

- [ ] `sets.json` 存在，两场都有 `axis` 和 `light`
- [ ] 两场都有 `blocking.jpg`，能看出谁站哪、机位在哪
- [ ] `validate_shots.py` 不再报 `没有 sets 注册表`

---

### T2 · 锁角色资产 + 统一 slug

**做什么**

1. 人名全部改成高棉 slug：`sophea`、`sara`、`piseth`、`ros`、`malis`、`davi`、`nita`、`som`、`pov`
   - 现在有三套并存（索菲娅 / Sofia / sophea），80 集下来资产必然对不上
   - 注意 `Pissa` ≠ `piseth`，`Sofia` ≠ `sophea`，是不同转写
2. 资产 key 改用 slug，UUID 作为 slug 的值存起来
3. **保镖还没有锁定资产** —— `sets.json` 的 `factory-office` 里有 `guard` 标记，但没有对应角色主图。补一个
4. 第 1 集有双人戏（`sophea`+`sara`、`piseth`+`sophea`、`ros`+`guard`），必须有身高图

**验收**

- [ ] 资产表用 slug 做 key，全流程无英化人名
- [ ] `guard` 有 face + master
- [ ] 双人戏有身高图，相对身高写进角色卡

---

### T3 · 修镜头图：换场硬切 + 末帧续判据

**做什么**

这是最关键的一项。当前 10 镜里 9 镜标 `continue`，串成一条直线，其中至少三处非法。

1. **SH009（罗丝走廊）改成 `cut: hard`**，`derived_from: factory-office.blocking`，
   `first_frame_source: blocking`。它和前八镜是两个空间，跨场用末帧续物理上不可能连续。
   > 旁证：你在 SH009 的 negatives 里写了 `not outdoor together` —— 那是在事后补漏。
   > 根因不在提示词，在图结构。
2. 给每镜加 `characters` 数组（T5 的前提）
3. 按人物交集判据重算每镜的 `first_frame_source`：

| 镜 | 父镜 | 交集 | 应为 |
|---|---|---|---|
| SH004 索菲娅首次出现 | SH003 校服单据 insert | 无 | `designed_frame` |
| SH007 皮萨 | SH006 索菲娅独自缝纫 | 无 | `designed_frame` |
| SH009 罗丝（换场） | — | — | `blocking`（硬切） |

无交集的镜头 `cut` 仍写 `continue`（地理和光位连续），但首帧不能用末帧。

**验收**

- [ ] `validate_shots.py` 的 `[GRAPH]` 分类零 ERROR
- [ ] 换场处 `cut: hard` + `derived_from: <scene>.blocking`
- [ ] 每镜有 `characters`，且 `first_frame_source` 与交集判据一致

---

### T4 · schema 迁移：枚举化 + 字段补全

**做什么**

1. `duration` → `seconds`
2. `setup` 改成枚举 `master`/`close`/`ots`/`insert`/`single`
   - 现在是自由文本（`"Rose through glass"`），把「哪一场」和「什么机位」混在一格里
3. `move` 改成枚举，**一镜一个运动**
   - `"static + gentle slow push-in"` → `push`
   - `"pan/push"` → 选一个
   - `"static + limited"` → `static`
4. `axis` 只能 `left`/`right`/`center`
   - `"slight left"` 是镜头微偏，不是轴线
   - **对峙戏必须让两人稳定分居两侧**：`piseth` 在 right，`sophea` 回应在 left
5. 补 `scale` / `facing` / `new_info` / `line` / `line_kind` / `caption` / `camera`
6. **`video_prompt` 搬进 JSON**（见 T6）

**验收**

- [ ] `[MIGRATION]` 和 `[SCHEMA]` 分类零 ERROR

---

## P1 · 质感（决定像不像导演拍的）

### T5 · 改 `look`：情绪形容词 → 光位

**做什么**

当前十镜的 `look` 全是情绪标签（`oppressive busy atmosphere`、`dignity strength`、
`restrained shock fate`），**没有一个字描述光。**

改成物理连续性：光位 / 景深 / 站位，必须能对着 blocking 检查。

- ✅ `头顶荧光冷白从上打，缝纫机工作灯暖黄从下打，车缝排在右`
- ❌ `heartbreaking helplessness`

情绪不写在这里 —— 新信息在 `new_info`，情绪由表演和景别承担。

**为什么要紧**

光位不锁死，相邻镜必然变色温。观众说不出哪里怪，只觉得假。
这是「AI 味」三大来源之一，且当前十镜**完全没有防线**。

**验收**

- [ ] 每镜 `look` 含光线描述，且与本场 `sets.light` 一致
- [ ] `[PROMPT]` 分类里 `look 里没有任何光线描述` 归零

---

### T6 · 提示词进 JSON + 台词归位

**做什么**

1. `video_prompt` 从第三份 MD 搬进 `shots.json`，≥80 字符。
   **JSON 是唯一真源，MD 由 JSON 生成。**
2. 台词从 `action` 里拿出来，放进 `line` / `caption`
   - SH005 的 `action` 现在是 `"Sofia says go to hospital I will finish for you"`，
     同镜 negatives 又写 `no lip-sync` —— 一边叫模型说话一边禁口型，自相矛盾
3. `negatives` 补齐五类：`orbit` / `crash zoom` / `face drift` / `clothing change` / `captions`
   - SH003 缺 `face drift` 和 `clothing change`；八镜缺 captions 类

**为什么必须搬进 JSON**

结构和指令分家等于没有校验。这三类问题在当前架构下**原理上查不出来**：
运镜措辞与 `move` 不一致、`orbit` 泄漏、台词泄漏。

**验收**

- [ ] `shots.json` 每镜有 `video_prompt`，MD 视图由它生成
- [ ] `[PROMPT]` 分类零 ERROR

---

### T7 · 修节奏：砍推镜、加长镜

**做什么**

把 `move` 归一到枚举后，当前配比暴露出来：

```
push×6  static×2  pan×1  track×1  pull×0     → 6/10 = 60%，超上限 40%
```

1. 把一部分推镜改成固定长镜或拉镜，`push` 占比压到 ≤40%
2. **全集至少一个 `pull`**。抄金标准 SH003：12 秒 master，从两人近景**拉回**车间全貌，
   同时皮萨从过道深处走进来 —— 一个动作同时完成呼吸和新人物入场
3. 每场至少一个真正 `static`
4. 镜长长短交错，不要机械均分（当前 `4,5,3,4,5,6,6,6,6,4` 平均 4.9 秒）
5. **删掉 ≤6 秒镜头上的 `split`**。`SH006` 和 `SH009` 都正好 6 秒，不需要拆；
   6 秒拆两段只是白多一个接点
6. 反过来，**做出真正的长镜并正确拆段**：>6 秒的镜拆同轴续段，
   `lens`/`axis`/`setup`/`move`/`look` 一字不改

**为什么要紧**

你禁了 `orbit` 和 `crash zoom`（对的），但把 push 写进了几乎每一镜 ——
环绕之后第二明显的 AI 味就是「镜头永远在缓慢前进」。

而且**每一刀都是一次让模型重新想象场景的机会**。当前 10 刀 49 秒、没有一镜超过 6 秒，
意味着从来没做过镜内调度，漂移机会被最大化了。

**验收**

- [ ] `[RHYTHM]` 分类零 ERROR 零 WARN
- [ ] 全集有 ≥1 个 `pull` 或 ≥8 秒长镜
- [ ] ≤6 秒的镜头没有 `segments`；>6 秒的都有，且段间五字段一致

---

## P2 · 流程闭环（决定能不能无人守跑 80 集）

### T8 · 音频换静音轨

**做什么**

在 clip 进入拼接前，把模型音频换成同长静音轨：

```bash
ffmpeg -y -i in.mp4 -f lavfi -i anullsrc=r=48000:cl=stereo \
  -map 0:v -map 1:a -c:v copy -c:a aac -b:a 128k -shortest out.mp4
```

**换成静音轨，不是删音轨。** 删掉会让审片轨报错（它要把 `[0:a]` 压低当背景床），
统一的流布局也让 `concat -c copy` 不会崩。

同时把末帧提取从 `-sseof -0.1` 改成 `-sseof -0.05`（离真正末帧更近，续接精度更高）。

**验收**

- [ ] `ffmpeg -i out.mp4 -af volumedetect -f null -` 的 `max_volume` ≈ -91 dB
- [ ] 音频流仍然存在（`ffprobe` 能看到 `codec_type=audio`）
- [ ] 拼接后成片里听不到 AI 人声

---

### T9 · 审片轨 + 双语成片

**做什么**

1. 出**带旁白和字幕的审片轨**（Gate E+）。无声切只能审脸，不能审剧情
2. 成片双轨：高棉语本地轨（主轨）+ 中文导出轨。两轨只换声和字幕，不换画面
3. 字幕后期叠，画面里不准出现生成的文字

这一项依赖 T6 的 `line` / `caption`，先做 T6。

**验收**

- [ ] 有一条能听见旁白、看见字幕的 ep01 审片轨
- [ ] 本地轨人名是高棉拼写，不是中文音译

---

### T10 · 把校验挂进流程，作为硬闸门

**做什么**

1. `validate_shots.py` 接进流程：**零 ERROR 才准进 Gate D**
2. 每集开跑前自动跑一次，不过就停，不要「先过再改」
3. 80 集要复用场景，建一份跨集的场景/覆盖模板库（剧本的制作提示已经把地点收敛到 7 个）

**为什么这是最后一项也是最重要的一项**

80 集 × 8–10 镜 ≈ 700 镜。人工逐镜过关卡在这个量级上不可能。
**写在文档里但机器查不到的规则，等于不存在。**

**验收**

- [ ] ep01 跑 `--warn-as-error` 退出码为 0
- [ ] 流程里有硬闸门，校验不过不会继续出图

---

## 完成判定

全部做完时，这条命令必须退出码 0：

```bash
python3 validate_shots.py --sets sets.json --shots ep01_shots.json --warn-as-error
```

然后拿 ep01 成片交本地抽检，抽检项：

1. 相邻镜的光位有没有变色温
2. 三个近景对角色 `face.jpg`，看脸有没有漂
3. 换场处是不是硬切，同场轴线有没有跳
4. 全集有没有「一直在慢推」的观感
5. 环境底噪在切镜头处有没有断

---

## 单集规格（已锁定，2026-08-24）

**60–75 秒 / 8–10 镜。** 80 集一致，不许逐集浮动。

之前三个来源不一致（剧本写 90–120 秒、本地 50–75 秒、云端实际 49 秒），现已定案。
49 秒装不下「一场冲突 + 一个钩子」的完整节拍 —— 当前 ep01 为了塞进 49 秒，
把 5 个节拍压成平均 4.9 秒一刀，这正是 T7 要修的碎切。
90–120 秒对竖屏留存不友好，且 80 集生成成本翻倍。

已写进 `validate_shots.py`，超出范围直接 ERROR：

```python
EPISODE_SECONDS = (60, 75)
EPISODE_SHOTS = (8, 10)
```

当前 ep01 的 49 秒会被判 ERROR，T7 必须把它拉进区间。
金标准 `gold/Episode1_shots.gold.json` 是 8 镜 64 秒，落在区间内。
