# 单镜提示词公式

给脚本专家第 4 步和分镜页 `video_prompt` 用。不是可灵/即梦整段广告词。

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
