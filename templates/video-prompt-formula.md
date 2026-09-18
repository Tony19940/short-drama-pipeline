# 单镜提示词公式

给脚本专家第 4 步和分镜页 `video_prompt` 用（MiniMax / H3 英文路线）。不是可灵/即梦整段广告词。

Seedance 中文路线不用这条公式：5.2 编译 `motion_prompt`，顺序 `geo_layout` → 每人一句 `descriptor` → 起点状态 + ACTION TIMING 按秒两拍（从 0.0s 就动）→ 运镜一句 → `audio_block`（声线卡 → 引号台词 → 动作 → 表情；不说话的人嘴闭着，只有环境声）→ 连戏句。只写肯定句，≤500 字。见 `knowledge/pipeline-pack/prompts/06_生成包_5.2.md`。

## 公式

`16:9 photoreal Khmer` + `lens` + `setup/scale` + **一次** `move` + `start pose -> one body beat -> hold` + `look` + `no subtitle / no lip-sync`

声音只写在 `line` / `caption` / `speaker`：口述、心里、旁白、出场简介、短信。动作必须是过程，不是「她站着好看」。一镜只做一件新信息。

派出时编译器会再包一层官方格式：Picture 1 对齐第 0 秒；有设计尾帧才写 Picture 2。`video_prompt` 不要自己写对白、配乐、硬切、另起海报。

## 合法例子

- static：Locked-off 35mm master, faint handheld breath. She holds the tray still. Same private-room tungsten.
- push：Slow 85mm push in, no orbit. He tips the box once and holds. Same aisle, sewing rows on the right.
- insert：Locked-off 85mm macro, no camera move. The broken silver bell rests against the collarbone.

## 不要写进 `video_prompt`

台词原文、环绕、闪摇、无人机、crash zoom、IMAX、配乐人名、口型、烧录字幕。画幅跟本剧 `confirm.md` 走，默认 16:9，不要写错成 9:16。
