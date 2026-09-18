# 角色联络板提示词

给 Gate B 的 inbox 任务单用。从已锁 `master.jpg` 改，禁止另开新脸。  
构图借飞书「人物角色设定图」；质感只借「可见毛孔、自然瑕疵、环境光」。瓷白、冷玉、仙气、古风五官不用。角色卡是参考图，不是成片画幅；成片默认 16:9。

## 文件

| slot | 画什么 | 父图 |
|---|---|---|
| `master` | 全身主图，本集默认装 | 只许全新一次 |
| `face` | 面部锁 | `master` |
| `front` | 全身正面，A 字站 | `master` |
| `side` | 全身左侧面，面朝左 | `master` |
| `back` | 全身背面 | `master` |
| `sheet` | 上排正/左/右/背，下排正脸+左脸+右脸 | `master` + 已有三视图 |
| 无头面板（试） | 正面全身，上缘切在下巴以下，只锁体型 / 服装 / 手；防中远景偷小脸 | `master`（`place_codex_asset.py` 暂无此 slot，手工落 `headless.jpg`） |

光照：同一方向、同一强度、同一柔和度。干净中性背景。不要情绪大光比。

锁 `master` 前先压力测试：从候选 edit 10 张不同姿势 / 光位 / 同框，≥9/10 认得出才落正式文件；认不出改角色卡的字再试。点改用蒙版只改那一块合回原图，图不整张过第二次模型。

## 质感（都市高棉）

Photoreal adult Khmer face, visible pores, natural skin texture, no beauty filter. Hair and cloth keep fabric wear. Match CULTURE.md: factory blouse / sampot / sbai as the card says. Olive-to-bronze default; Sophea may be fair-tender Khmer, not porcelain.

## 禁止

另开新脸、换发色、换年龄、旗袍、网红磨皮、ARRI 宽银幕、画上字幕。

## 出关键帧时怎么用

出关键帧时按本镜 camera_id / 机位方位点名面板：正 / 左侧 / 右侧 / 背；越肩、反打用侧板，不用正脸板。
