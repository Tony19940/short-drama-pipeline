# 导演层 · 场合同拆镜

拆镜 Agent 是导演层的发动机。它不写故事、不出视频。它只决定这场戏拍哪些镜头。5.1 说明书和 5.2 生成包是后面两岗，不要写进这一岗。
人先审整场，再锁单镜。提示词是合同的译文，不是另写的作文。

对照：Toonflow / LocalMiniDrama 的画布当视图；Jellyfish 的镜头准备态；
shuohao 的「分镜只输出」和 2-5 秒对白门；BigBanana 的首尾帧；drama-skills 的人确认后才投产。

## 留下

- 真源仍是 productions/<slug>/
- 人锁关卡；草稿先于正式表
- 舞台 / blocking.jpg / 第 0 秒 start
- 从父图改，不准另开新脸
- 对白不进 video_prompt
- H3 三字段、出片指纹、Ken Burns 禁令

## 扔掉

- 覆盖表一行自动变一镜、机位轮换、默认全 static
- 只审单镜、提示词可抄上一镜
- 换机位就当新海报
- 把 concat 全长拼接当成导演完成

## 拆镜依据

1. 已锁的本、场次、舞台、主图。不许再编情节。
2. knowledge/director/playbook.md：永远生效的短打法。
3. knowledge/cases/：拉片蒸馏的场型卡，一场只用最像的一两张。
4. 写字模型只填句。刀法不来自模型记忆。

## 一场合同

每场先定轴和 2-3 个机位（另加 insert）。镜头必须挂 rig_id。
对白镜跟台词走；邻镜写成动作对；video_prompt 必须含本镜 action。
续镜第 0 秒 start 必须已经在动作中间，不能站好再开始。
对白/心里台词后插 2 秒无台词反应镜。
每镜合同带 handle=2 / render_seconds=seconds+2，给以后的 EDL 留修剪余地；assemble.sh 这期仍全长拼接。
写字模型只填句。没有密钥时启发式填 start/action/landing，禁止按剧情关键词写死英文。

## 文件

| 文件 | 谁写 |
|---|---|
| knowledge/director/playbook.md | 手册 |
| knowledge/cases/*.md | 场型卡 |
| 03-storyboard/shots.draft.json | 拆镜草稿，带 directing / scenes / shots |
| 03-storyboard/shots.json | 人接受后的正式表 |

Gate C 对 directing=scene-rig-v1 的新表执行硬检查；旧正式表只警告，不挡 003/004/005 回归。
005 已锁成片和正式分镜先不动。新草稿走新刀法。

