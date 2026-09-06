# 合法运镜词库

给 Gate C 和脚本专家用。`shots.json` 的 `move` 只许下面五个。  
来源压缩自飞书「九大连续运镜 / 十大运镜 / 60组运镜」，只留下竖屏都市剧能执行的句子。

## 合同

| move | 中文 | `camera` / `video_prompt` 用这句 | 借自 |
|---|---|---|---|
| `static` | 定镜 + 呼吸 | locked-off static camera, faint handheld breath only, no orbit | 手持呼吸；固定镜头 |
| `push` | 慢推 | slow push in on one subject, faint handheld, no orbit, no crash zoom | 轨道推；85mm 推近 |
| `pull` | 慢拉 | slow pull out to restore room geography, faint handheld, no orbit | 推近后再拉回中景 |
| `pan` | 一次横摇 | one small pan along the 180 line, then hold; no whip pan | 慢摇；光影交界可停一下 |
| `track` | 短横移 | short lateral track, keep background continuous, optional foreground wipe | 轨道横移 + 前景遮挡 |

速度副词只用：slow / faint / hold。不要写 2x、急速、螺旋。

## 一场里怎么排

- master 默认 `static` 或一次 `pull` 回全貌。
- close / 认脸 / 银铃 用一次 `push`。
- 同场不要连续两镜都 `push`。
- 手持只保留呼吸感，关键动作可以 hold，不要剧烈晃。

## 禁表（写进合同即 `check_storyboard.py` 失败）

环绕 / 360 wrap / orbit / 无人机俯冲 / 螺旋下降 / 闪摇 whip pan / crash zoom / MOCO 机械臂 / 俯拍旋转加速 / 航拍云海 / IMAX / 16:9。

这些可以留在参考片反推里当「原片做了什么」，改成本集合同时必须换成上表五选一。
