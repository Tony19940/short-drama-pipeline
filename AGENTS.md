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
| 设计首帧（planned_start） | `productions/<slug>/04-frames/SH001.jpg` |
| 设计尾帧（planned_end，可选） | `productions/<slug>/04-frames/SH001-end.jpg` |
| 视频实际尾帧（generated_end，渲染器抽取） | `productions/<slug>/05-shots/SH001-last.jpg` |

带集标签时，两类目录都使用本集子目录，如 `04-frames/ep01-v2/` 和 `05-shots/ep01-v2/`。旧 `04-frames/SH001-last.jpg` 不搬动；`--slot last` 保留兼容，但落盘角色仍是 **planned_end**，不会变成视频实际尾帧。缺角色元数据的旧文件标为 `unknown/legacy`，不能凭文件名宣称实际视频已到达该状态。

关键帧不是护照。从该场空镜或上一镜已锁帧 **edit**，禁止文生新脸。父图只参考人物和场景，**不跟父图文件比例走**。画幅跟生成包 / 本剧 confirm 走（本集 16:9）。`place_codex_frame.py` 拒绝比例不符的源图；可用 `--crop` 裁切，再等比缩放到正式尺寸，禁止拉伸。
**首帧 = 动作起点状态。** `one_action` 的动词可以已起手（手已伸出 / 身已前倾 / 已在挥 / 门已在裂），禁止结果（已入手 / 已落地 / 已打开 / 已入袋）。同机位优先从上一镜来源已核实、过身份审的实际尾帧 edit；还未生成视频时可从设计尾或已过闸首帧作视觉参考，但不能据此声称视频状态连续。内容跟本镜 `in_from` / `still_start`，不跟父图已经做完的结果（SH006 父图 SH005 钥匙仍在地上 — 父图对，子图可以画她已俯身伸手，钥匙仍在地上；画成入手就错了）。实际尾与本镜起点不符时先报告状态差异，不靠换文件名消除。换机位重新锚定，避免沿用上一机位构图。脸按肌肉画，不写情绪词；不说话的人嘴闭着。
生成包每镜有 `state_note`（连戏句）和 `continuity.binding`（绑法），逐字照做：反剪就画反剪，说不在画里的就不画。

```bash
python3 scripts/place_codex_frame.py \
  --prod productions/009-siem-reap \
  --shot SH001 --slot first \
  --parent 02-assets/scenes/modern-channel/master.jpg \
  --src "$CODEX_HOME/generated_images/那张图.png"
```

`--parent` 首帧默认同机位上一镜已核实实际尾；没有时用设计尾（优先 `-end.jpg`，再兼容 `-last.jpg`），再用已过闸首帧，并输出角色/来源提示。空镜 `master.jpg` 只许场第一镜、新机位重新锚定，或加 `--allow-master`。设计尾用 **`--slot end`**，默认父图是本镜首帧。脚本在 jpg 旁写 JSON，记录 `frame_role`、父图角色及来源、文件 hash。实际尾的 sidecar 由渲染器抽帧成功后记录，绑定源视频和尾帧 hash；任一文件改变即失效。来源核实与身份/内容审查分别进行，抽到尾帧不等于审核通过。

不要把首帧写进 `02-assets/`。不要写 `shots.json`。不要出视频。不要自己写 `keyframes.json` 的 pass。
