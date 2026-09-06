# 直接粘给云端 agent 的第三轮结果（资产注册表）

> 附上更新后的 `validate_shots.py`（新增 `--assets` 交叉校验）。

---

资产注册表收到了。**T2 的两个硬缺口都补上了** —— `guard`（保镖）有了主图，
`factory-floor` / `factory-office` 有了 blocking。slug 全部是高棉小写，和本地锁定资产一一对得上。
`name_km` 是加分项，本地轨字幕正好要用。`chando` 也提前建好了。

我给校验器加了一层 `--assets` 交叉校验，因为 80 集独立生产最怕的就是**分镜引用了不存在的资产**：
脚本不会报错，模型会默默凭空造一个人或一个空间，等成片出来才发现。

```bash
python3 validate_shots.py --sets sets.json --shots ep01_shots.json --assets assets.json
```

跑完当前三份：**ERROR 7 / WARN 3。** 分镜那 5 条还是上一轮的（未改），资产层新增 2 条 ERROR。

## 资产层还缺两样（都是 ERROR）

### 1. 没有 scale 身高图

ep01 有 3 组双人以上同框：`sara+sophea`、`piseth+sophea`、`guard+ros+sophea`。

模型不会自己记住谁高。没有身高图，同一集里索菲娅可能第 2 镜比萨拉矮、第 6 镜比皮萨高。
这类错误观众一眼能看出来，但很难归因，通常只会觉得"假"。

**要的是**：每组常同框组合一张身高图，脚在同一地平线上，相对身高写进角色卡。
本地这一集用了四张（`scale-factory`、`scale-heirs`、`scale-men`、`scale-parents`），
按组合归类而不是按集，80 集可以复用。

### 2. 没有 props —— 银铃没锁

这一条比看起来严重得多。

**半枚莲花银铃是贯穿 80 集的身份信物。** 而且第 12 集有一场戏要求两半合在一起、
**断口严丝合缝**（罗丝："这是我亲手给孙女打的"）。如果银铃不是锁定资产，
每一集它的形状、纹路、断口都会不一样 —— 那场戏在物理上就拍不成。

ep01 的钩子本身也是它。

**要建的 props**（至少 ep01–ep20 会用到的）：

| slug | 说明 |
|---|---|
| `bell-half-sophea` | 索菲娅那半枚，断口形状必须固定 |
| `bell-half-ros` | 罗丝珍藏那半枚，断口与上者互补 |
| `watch-neary` | 阿莲旧女表，表针停在 3:17 |
| `ledger-blue` | 蓝色账本 |

银铃两半必须**一次生成、成对锁定**，不能分两次各生成一个 —— 否则断口对不上。

## 三条 WARN

**`sophea` 的 `root_face` 和 `root_full` 是同一个 UUID。**
近景要的是紧脸裁切，全身要管服装和身形，一张顶两用会两头都弱。拆成两张。

**12 个角色只有 `root`，没有 `root_face`。**
`chando`、`davi`、`guard`、`malis`、`neary`、`nita`、`piseth`、`pov`、`ros`、`sara`、`sokha`、`som`。
键名不统一，「脸优先挂参考图」这一步就无法自动化 —— 画布编辑节点上限 3 张，
必须能程序化地取到每个出场角色的脸。建议统一成每个角色都有 `root_face` + `root_full`。

**SH002 是 `sara` 的近景，但她只有 `root`。** 近景用全身图当参考，脸会糊。

## 另外两点

**`factory-gate` 和 `vira-house` 只有 master，没有 blocking。** ep01 用不到，不报错。
但按 Gate S，没有 blocking 不准写该场镜头 —— 用到它们的那一集之前要补上。

**角色卡信息只有 `sophea` 齐全。** 只有她有 `age` 和 `notes`（装、发型、银铃）。
80 集要按场次换装，而换装必须是**从 master 改**，不是重新生成 —— 所以每个角色都要有
`notes` 记住原始装束和标志物，否则改到第 30 集就漂了。年龄也要写（本地规则：成人角色必须明确成年，
避免出幼态脸）。

## 下一步

资产层补 scale 和 props 这两项，分镜层改上一轮那 5 条（空景开场、SH002 末帧、
第二场缺 insert 和钩子特写、总长 58s、`seconds_total` 对不上）。

两边都改完跑：

```bash
python3 validate_shots.py --sets sets.json --shots ep01_shots.json --assets assets.json --warn-as-error
```

退出码 0 就可以进 Gate D 出首帧了。

---
