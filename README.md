# 短剧生成流水线

对照小云雀短剧 Agent：**剧本 → 确认画风/画幅/旁白 → 蓝图/资产 → 舞台机位 → 覆盖分镜 → 末帧续出片 → 审剧情声画**。

不是一键成片，也不是「静帧动 6 秒再拼接」。人审卡点。完整对照 [XIAOYUNQUE.md](XIAOYUNQUE.md)。

当前主项目是 **高棉故事 100 集**，总簿在 [`productions/khmer-stories/`](productions/khmer-stories/)。都市短剧样片在 `productions/002-sophea-tent/`。

## 你怎么用

1. 合集先看 `productions/khmer-stories/CATALOG.md`，点一集。
2. 复制 `productions/_template` 开新集，或继续用已有 `productions/<slug>`。
3. 写 `confirm.md`（画风/画幅/旁白）和 `blueprint.md`，先讨论，不生图。
4. 锁主图。然后写 `sets.json`，跑 `render_blocking.py` 得到舞台。没有 blocking 不准写镜头。
5. `coverage.md` 一场几种机位 → `shots.json` → `python3 scripts/check_prod.py --prod …`。continue 出片吃上一镜末帧。审剧情用 `mix_review_track.py`，不要拿无声 H3 当审片。

规则见 [PIPELINE.md](PIPELINE.md)、[CULTURE.md](CULTURE.md)、[QUALITY.md](QUALITY.md)（硬规则 **R1–R12**）。出片见 [VIDEO.md](VIDEO.md)。

## 目录

```
templates/          可复用卡片
productions/
  _template/        新剧空壳
  khmer-stories/    100 集总簿
  001-wip/          神话旁白集《牵披肩》
  002-sophea-tent/  都市短剧样片《厂服进店》
```

每部剧内部：

| 目录 | 关卡 | 你审什么 |
|---|---|---|
| `01-bible/` | Gate A | 剧本、confirm（画风/画幅/旁白）、蓝图 |
| `02-assets/` | Gate B | 角色/场景主图；每场 `blocking.jpg` |
| `03-storyboard/` | Gate S/C | `sets.json` 舞台 → `coverage.md` 覆盖 → `shots.json` |
| `04-frames/` | Gate D | 从 blocking 或上一镜改的首帧 |
| `05-shots/` | Gate E | 单镜视频；continue = 上一镜末帧 |
| `06-export/` | Gate E+/F | 审剧情切 `preview-*-vo.mp4`；成片 |
| `07-narration/` | Gate F | 成片轨旁白 |

## 能力边界

- **文本**：剧本、蓝图、角色卡、分镜表。
- **图片**：先出一张主图，后续变体全部锚定这张图，避免换脸。
- **视频**：按镜切。默认 Hailuo 2.3 Fast 无声；每集最多 3 镜 H3，且必须带角色主图作参考。见 `VIDEO.md`。
- **成片**：ffmpeg 拼接画面，再叠旁白和字幕。不对口型。旁白更长时拉长画面，不加速人声。

都市短剧默认 **50–75 秒，6–10 镜**；神话旁白集仍可 **70–90 秒，8–15 镜**。100 集合集按季复用主图，不平行开三季。


## 本机导演台

第一期控制台在 `studio/`，直接操作 `productions/003-sreymom-engagement`：

```bash
bash scripts/run_director.sh
```

打开 [http://127.0.0.1:3101](http://127.0.0.1:3101)。关卡、父镜改图、GPU 出片规则见 [STUDIO.md](STUDIO.md)。

第 01 集的导演合同在 `03-storyboard/shots.json`：`video_prompt` 才是给模型的镜头说明书。出图把文件丢进 `productions/003-sreymom-engagement/.director/inbox/`，扫描后只进候选。
