# 交给云端 agent 的东西

## 发这五个文件

| 文件 | 作用 |
|---|---|
| `CLOUD-REBUILD-TASKS.md` | **一次性改造任务单**，按 T0→T10 顺序做，每项有验收命令 |
| `CLOUD-PIPELINE.md` | **长期规则**，每次开工前读，不是一次性任务 |
| `DIAGNOSIS-ep01.md` | 诊断报告与证据，说明每条规则为什么存在 |
| `validate_shots.py` | 校验器，单文件零依赖，直接放进云端流程 |
| `gold/` | 金标准样例：`sets.json` + `Episode1_shots.gold.json` |

`incoming/` 是它发来的原始产物，留档用，不用回传。

## 怎么交代

`PASTE-TO-CLOUD-AGENT.md` 里有一段可直接整段粘贴的话，附上上面五个文件即可。
它已经把三件最要紧的事讲在前面（自我诊断方向反了、三个未自查到的质感问题、已锁定的单集规格）。

## 现状

```bash
python3 validate_shots.py --shots incoming/Episode1_shots.cloud.json
# 镜头 10 个，总长 49s / ERROR 225 条 / WARN 2 条

python3 validate_shots.py --sets gold/sets.json --shots gold/Episode1_shots.gold.json --warn-as-error
# 镜头 8 个，总长 64s / ERROR 0 条 / WARN 0 条
```

金标准能过，说明规则可满足，不是刁难。

## 单集规格（已锁定 2026-08-24）

**60–75 秒 / 8–10 镜**，80 集一致。已写进校验器，超范围直接 ERROR。
云端 ep01 的 49 秒低于下限，T7 要拉进区间。

## 本地这边的对应文件

云端是 API/工具链路线，本地是同一套导演层的手动与 API 双路线：

- `PIPELINE.md` —— 本地关卡
- `GROK-CANVAS.md` —— 画布手动路线
- `scripts/check_storyboard.py` —— 本地 Gate C2 校验（`validate_shots.py` 的来源）
- `scripts/ingest_shots.py` —— mp4 回流 + 末帧提取 + 静音轨（T8 的参考实现）
