# 状态

- **关卡**：Gate B 已锁。镜头表已加逐镜 `state`。5.2 生成包已确认（`confirmed=true`，确认时尚为换风格前的图）。**6.1 已过（换风格后重签）**：`keyframes.json` origin=`human-qc-ep01-restyle-r1`，21 镜 pass，`reviewed_by=tonyteacher`。五处硬伤已重出并过静帧。未出本轮视频
- **圣经**：8 集已写入
- **第 1 集分镜（已锁定）**：`03-storyboard/shot-list.md` + `.pipeline/shot_list.json`（schema `shot-table-v2`，**21 镜 / 136 秒**，Seedance 2.0）。每镜带 `state` + `state_changes`，`validate_state_chain` 过
- **目标模型**：Seedance 2.0。换模型只重编译生成包，不重拆镜
- **资产**：Ep01 Gate B 21 张正式 jpg 已齐。`.pipeline/assets.json` status=ready
- **生成包**：`.pipeline/gen_packages.json` 21 条已确认（tonyteacher）。每条带 `state` / `state_note` / `continuity.binding`。未写 `03-storyboard/shots.json`
- **首帧交接**：第二轮 `03-storyboard/HANDOFF-FRAMES-EP01-R2.md`（5 镜 8 张）。落盘 `scripts/place_codex_frame.py --parent …`，会在 jpg 旁写溯源 json
- **首帧 / 成片**：`04-frames/` 36 张正式 jpg（历轮旧版在对应 `-vN.jpg`，每张带溯源 json）。`keyframes.json` v2 整单重签，7 个近景补了 `plastic_face`+`anatomy`，15 个 first_last 补了 `out_to_readable`，全镜补 `state_match`。SH002/SH003/SH010/SH012/SH013/SH014 六条 nit 由 tonyteacher `waived_by` 放行。生成包 `keyframe_files` 仍为空
- **审阅页**：`REVIEW.html`（父图 → 起幅 → 落幅 + 状态句 + fail/nit）。改图后重跑 `python3 scripts/render_frame_review.py --prod productions/009-siem-reap`

- **第 2 集分镜（草稿，未锁）**：`03-storyboard/shot-list.ep02.md` + `.pipeline/shot_list.ep02.json`（23 镜 / 158 秒，`shot-table-v2`）。舞台轴在 `03-storyboard/sets.ep02.json`。不要覆盖第 1 集 `shot_list.json`。开场绑法已和第 1 集落幅对齐（草绳绑柱，不是麻绳）。第 2 集出图等第 1 集新风格资产稳定后再做。

下一件：第 1 集继续新风格资产/首帧；第 2 集分镜表等人锁。不要写 `shots.json`。6.2 出片仍未提交。
