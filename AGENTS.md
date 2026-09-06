# Codex 在本仓库怎么出资产图

人物、场景、道具图不走导演台 Imagine，也不走 inbox 当主路径。
你在 Codex 里直接生图，落到 `productions/<slug>/02-assets/`。导演台资产页每 4 秒读盘，刷新就能看见。

## 路径

| 种类 | 正式文件 |
|---|---|
| 角色主图 | `productions/<slug>/02-assets/characters/<id>/master.jpg` |
| 角色脸 | `.../face.jpg` |
| 正侧背 | `.../front.jpg` `side.jpg` `back.jpg` |
| 联络板 | `.../sheet.jpg` |
| 场景空镜 | `productions/<slug>/02-assets/scenes/<id>/master.jpg` |
| 道具 | `productions/<slug>/02-assets/props/<id>/master.jpg` |

`master` 只许全新一次。正侧背、脸、联络板必须从已有 `master` 改，禁止另开新脸。
已有正式文件不要直接覆盖；用 `place_codex_asset.py`，它会把旧图留成 `master-v1.jpg`。

## 出图步骤

1. 读该角色/场景卡和 `02-assets/LOOK.md`。
2. 用内置 imagegen 生图。非 master 先 `view_image` 看父图再 edit。
3. 把生成文件落到正式 jpg：

```bash
python3 scripts/place_codex_asset.py \
  --prod productions/004-yuye-jinlian \
  --kind character --slug sophea --slot face \
  --src "$CODEX_HOME/generated_images/那张图.png"
```

4. 不要把 `sheet-candidate-*` 自动晋升成 `sheet.jpg`。
5. 不要写 `03-storyboard/shots.json`。

## 路径（6.1 关键帧）

| 种类 | 正式文件 |
|---|---|
| 首帧 | `productions/<slug>/04-frames/SH001.jpg` |
| 尾帧 | `productions/<slug>/04-frames/SH001-last.jpg` |

关键帧不是护照。从该场空镜或上一镜首帧 **edit**，禁止文生新脸。画幅跟生成包走（本集 16:9）。
生成包每镜有 `state_note`（连戏句）和 `continuity.binding`（绑法），逐字照做：反剪就画反剪，说不在画里的就不画。

```bash
python3 scripts/place_codex_frame.py \
  --prod productions/009-siem-reap \
  --shot SH001 --slot first \
  --parent 02-assets/scenes/modern-channel/master.jpg \
  --src "$CODEX_HOME/generated_images/那张图.png"
```

`--parent` 首帧必填（本场空镜 `master.jpg` 或上一镜已锁的 `04-frames/SHxxx.jpg`），尾帧默认本镜首帧。脚本在 jpg 旁写 `SHxxx.json` 记父图与来源。

不要把首帧写进 `02-assets/`。不要写 `shots.json`。不要出视频。不要自己写 `keyframes.json` 的 pass。

