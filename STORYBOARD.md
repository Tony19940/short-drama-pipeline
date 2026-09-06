# 舞台、覆盖、分镜

先读 `XIAOYUNQUE.md`。这里只写 Gate S / C1 / C2 怎么填。

**走导演台流水线的项目**（`.pipeline/` 有 JSON）：分镜由镜头表岗一次拆完，schema `shot-table-v2`，字段见 `knowledge/pipeline-pack/交接字段表.md` 第 4 节，提示词在 `knowledge/pipeline-pack/prompts/04_分镜设计.md`，能力档在 `scripts/director/video_profiles.py`，可拍性校验在 `scripts/director/shot_table.py`。校验通过后自动出 `03-storyboard/shot-list.draft.md` 给人审。下面的 `shots.json` 合同仍是旧路径（直接手写 / 反推项目）。

## Gate S · 舞台 `sets.json`

一场一个 id，对应 `02-assets/scenes/<id>/`。

```json
{
  "id": "shop-wedding",
  "master": "02-assets/scenes/shop-wedding/master.jpg",
  "blocking": "02-assets/scenes/shop-wedding/blocking.jpg",
  "axis": "巷子向店门，金椅在左前",
  "marks": [
    {"id": "sophea", "x": 0.72, "y": 0.62, "note": "椅外，看席"},
    {"id": "chenda", "x": 0.38, "y": 0.70, "note": "挡在椅前"},
    {"id": "vireak", "x": 0.45, "y": 0.55, "note": "供桌一侧"},
    {"id": "camera", "x": 0.50, "y": 0.95, "note": "与 master 同一轴"}
  ]
}
```

`python3 scripts/render_blocking.py --prod …` 把点打在空镜上，得到 `blocking.jpg`。  
**没有 blocking，不准写该场镜头。**

## Gate C1 · 覆盖 `coverage.md`

一场戏是句子，镜头是单词。覆盖表先于 `shots.json`。

都市短剧一场至少：

- 1 个 `master`（地理：谁在哪）
- 1 个更紧的机位（`close` 或 `ots`）打情绪
- 需要才 `insert`（短信、ABA、钱）

禁止：Sophea 一张全身、Chenda 一张全身、Vireak 一张全身。那是选角册。

## Gate C2 · 分镜合同

每镜必填（都市短剧）：

| 字段 | 含义 |
|---|---|
| `scene` | 对应 sets.json 的 id |
| `setup` | `master` / `close` / `ots` / `insert` / `single` |
| `move` | `static` / `push` / `pull` / `pan` / `track` |
| `derived_from` | 该场第一镜：`<scene>.blocking`；续：上一镜 id |
| `from` `cut` | 同场 continue；换场 hard |
| `scale` `facing` `expression` | 景别朝向表情 |
| `new_info` | 这几秒观众新知道的一件事 |
| `line` `line_kind` `caption` `speaker` | 口述/心里/旁白/出场简介/短信。对白不准进 video_prompt |
| `speaker` | 口述或心里台词才填角色 slug；旁白/简介留空 |
| `last_frame` | 出视频后抽出的末帧，同机位续才拿去当下一起点 |
| `end_frame` | 可选设计尾帧，如 `04-frames/SH004-end.jpg`。动作要收住才填。禁止写成 `{id}-last.jpg` |
| `lens` | `35mm` / `50mm` / `85mm` |
| `axis` | `left` / `right` / `center`；同场有人物交集时禁止左右对调 |
| `camera` | 一句：固定 / 呼吸手持 / 慢推 / 一次横摇 |
| `action` | 这几秒身体做的一件事 |
| `look` | 光线、背景虚实、站位，必须能对上 blocking |
| `video_prompt` | 编译给 H3/Imagine 的英文镜头说明书；对白不准写进来 |
| `start` | 第 0 秒站谁、坐/站、工位还是过道、手里拿什么。不能抄 action / new_info，也不能写 on … marks |
| `negatives` | 本镜禁止项 |

`prompt` 留短句。真正出图出片用 `video_prompt`。AI 草稿写到 `shots.draft.json`，人接受后才覆盖正式表。

同场同人同景别禁止连排。同人同景别再同朝向也不行。

道具 `insert` 之后的人物镜，`from` 可以跳过 insert，回到 insert 之前的人。

## 声音轨（都市短剧强制）

短剧靠声音让观众 3 秒入戏，不靠烧在画面上的字。`video_prompt` 仍然禁对白、禁口型。

| `line_kind` | 中文 | 谁说 | 写什么 |
|---|---|---|---|
| `intro` | 出场简介 | 旁白 | 前 12 秒内一次：人名 + 身份。一集只许一条 |
| `dialogue` | 口述台词 | `speaker` | 角色嘴里的狠话/求情，短句 |
| `inner` | 心里台词 | `speaker` | 不张嘴。恐惧、盘算、认出 |
| `narration` | 旁白 | 空 | 作者告诉观众的设定/钩子 |
| `sms` | 短信/字卡 | 空 | 手机、工牌、罚款单上的字 |

规则：

1. 每镜必须有 `line` + `caption`。`caption` 是后期字幕，不是画面里的字。
2. 口述/心里可填 `speaker`（角色 slug 或 `offscreen`）。旁白、简介、短信不许填 speaker。旧分镜没有 speaker 仍可通过。
3. 一镜只推进一件新信息；声音也只做一件事。不要同一镜又简介又吵架。
4. 开场 12 秒内必须出现冲突，并尽量给一条 `intro` 或一句能立住身份的口述。
5. 对白后期叠，不赌口型。H3 人声不当配音。

静帧只描述 `start`：从父图改、只改一件事、不要把走过来/砸箱/推镜写成已经发生完。`action` / `video_prompt` 管出片过程。同场 `continue` 的 `start` 必须和上一镜不同。

## Gate D / E

| 时机 | 首帧从哪来 |
|---|---|
| 一场的第一镜 | `image_edit` 该场 blocking |
| 场内续、还没有视频 | `image_edit` 上一镜首帧 |
| 场内续、同机位、人物有交集、已有 `{from}-last.jpg` | **FL2VA 吃上一镜真末帧** |
| 场内续、换机位（master↔close 等） | **用这一镜锁定首帧**，不吃上一镜末帧 |
| 换场硬切 | 新场 blocking |
| 本镜写了 `end_frame` 且文件在 | **FL2VA 首帧 + 设计尾帧**。抽出的 `-last.jpg` 不算设计尾帧 |
| 有 `sheet.jpg` / `face.jpg` | 仍锁首帧；参考图外挂 Ref2VA，不替代第 0 秒 |

禁止每张都正面站好看镜头。
