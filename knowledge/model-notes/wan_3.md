# 模型经验 · 万相 3.0（阿里云百炼 wan3.0-video）

核对日 2026-09-10。事实源：百炼文档 [万相3.0视频生成API参考](https://help.aliyun.com/zh/model-studio/wan3-video-generation-api-reference)。本仓库已接 HTTP 异步任务，未付费出片。

## 接入

| 项 | 值 |
|---|---|
| 模型 | `wan3.0-video`（标准）/ `wan3.0-video-prime`（高速） |
| 地域 | 本账号 `cn-beijing` |
| 创建 | `POST {workspace}.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis` |
| 查询 | `GET {workspace}.cn-beijing.maas.aliyuncs.com/api/v1/tasks/{task_id}` |
| 头 | `Authorization: Bearer $DASHSCOPE_API_KEY`，`X-DashScope-Async: enable` |
| 脚本 | `scripts/video_backends/wan3.py` |

环境变量：`DASHSCOPE_API_KEY`、`DASHSCOPE_WORKSPACE_ID`、`DASHSCOPE_REGION`、`WAN_MODEL`、`WAN_RESOLUTION`。

## 能力

| 项 | 文档 | 本仓库 |
|---|---|---|
| 时长 | 无视频输入时 2–30 秒整数；`-1` 智能时长 | 只校验 2–30，不替人改；不编 `-1` |
| 分辨率 | 480P / 720P / 1080P，默认 1080P | 测试默认 720P |
| 首帧 / 首尾帧 | `media.type=first_frame` / `last_frame`，ratio 建议 adaptive | i2v / flf 强制 adaptive |
| 参考图 | 最多 10 张 `reference_image` | 硬首帧丢掉 refs，身份靠 6.1 父图链 |
| 互斥 | first_frame / last_frame 不能和 reference_image 同发 | 与 H3 / Seedance 2.5 同一条 |
| 声音 | `audio` 默认 true，开关同价 | 本剧默认 false，对白后期叠 |
| 改写 | `prompt_extend` 默认 true | 默认 false，避免改掉已锁 motion |
| 水印 | API 默认 false | false |
| 图输入 | 公网 URL、OSS 临时 URL、或 data URL | 本地 jpg 走 data URL |

文生视频不是成片路径。试镜写到 `05-shots/smoke-wan/`，不覆盖正式 `05-shots/SHxxx.mp4`。

## 种子

| 现象 | 原因 | 处理 |
|---|---|---|
| 首帧和护照图同发被拒 | first_frame 与 reference_image 互斥 | 硬首帧只发 first_frame |
| 透明 PNG 被拒 | 文档不支持透明通道 | 用 jpg 首帧 |
| prompt 被改飞 | 默认 prompt_extend=true | 成片路径关改写 |
| 导演台误走万相 | 只因为配了 DASHSCOPE_API_KEY | 默认路由不抢；要测时 `--backend wan` 或 `DIRECTOR_VIDEO_BACKEND=wan` |
