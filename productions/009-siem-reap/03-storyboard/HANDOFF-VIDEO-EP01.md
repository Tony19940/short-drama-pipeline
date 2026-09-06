# 第 1 集 6.2 出片准备（Seedance 2.0 Mini 480P）

本文件是正式出片前的交接，不是成片。**不要写 `shots.json`。**

入口：

```bash
python3 scripts/render_seedance_packages.py \
  --prod productions/009-siem-reap \
  --dry-run
```

真出片时去掉 `--dry-run`，可加 `--only SH001`。抽出的尾帧写到 `05-shots/SHxxx-last.jpg`，不覆盖 `04-frames/SHxxx-last.jpg`。

- 镜头数：21
- 可派：21
- 最难：SH004, SH013, SH019
- 模型 / 分辨率：以 `.env` 的 `ARK_SEEDANCE_MODEL` / `ARK_RESOLUTION` 为准（当前约定 Mini + 480P）

| 镜 | 模式 | 秒 | 首帧 | 设计尾帧 | 身份参考 | 最难 | 状态 |
|---|---|---:|---|---|---|---|---|
| SH001 | flf2v→flf | 5 | `04-frames/SH001.jpg` | `04-frames/SH001-last.jpg` | `02-assets/characters/sokha/master.jpg` |  | 可派 |
| SH002 | i2v_first→i2v | 4 | `04-frames/SH002.jpg` | `—` | `02-assets/characters/sokha/master.jpg`, `02-assets/characters/sokha/face.jpg` |  | 已有 mp4，将跳过 |
| SH003 | flf2v→flf | 6 | `04-frames/SH003.jpg` | `04-frames/SH003-last.jpg` | `02-assets/characters/sokha/master.jpg`, `02-assets/characters/sokha/face.jpg` |  | 可派 |
| SH004 | flf2v→flf | 8 | `04-frames/SH004.jpg` | `04-frames/SH004-last.jpg` | `02-assets/characters/sokha/master.jpg` | 是 | 可派 |
| SH005 | flf2v→flf | 5 | `04-frames/SH005.jpg` | `04-frames/SH005-last.jpg` | `02-assets/characters/sokha-wet/master.jpg` |  | 可派 |
| SH006 | flf2v→flf | 5 | `04-frames/SH006.jpg` | `04-frames/SH006-last.jpg` | `02-assets/characters/sokha-wet/master.jpg`, `02-assets/characters/sokha-wet/face.jpg` |  | 可派 |
| SH007 | flf2v→flf | 5 | `04-frames/SH007.jpg` | `04-frames/SH007-last.jpg` | `02-assets/characters/sokha-wet/master.jpg`, `02-assets/characters/sokha-wet/face.jpg`, `02-assets/characters/yunlong/master.jpg`, `02-assets/characters/yunlong/face.jpg` |  | 可派 |
| SH008 | flf2v→flf | 9 | `04-frames/SH008.jpg` | `04-frames/SH008-last.jpg` | `02-assets/characters/sokha-wet/master.jpg`, `02-assets/characters/sokha-wet/face.jpg`, `02-assets/characters/yunlong/master.jpg`, `02-assets/characters/yunlong/face.jpg` |  | 可派 |
| SH009 | flf2v→flf | 9 | `04-frames/SH009.jpg` | `04-frames/SH009-last.jpg` | `02-assets/characters/sokha-wet/master.jpg`, `02-assets/characters/sokha-wet/face.jpg`, `02-assets/characters/yunlong/master.jpg`, `02-assets/characters/yunlong/face.jpg` |  | 可派 |
| SH010 | flf2v→flf | 6 | `04-frames/SH010.jpg` | `04-frames/SH010-last.jpg` | `02-assets/characters/sokha-wet/master.jpg`, `02-assets/characters/yunlong/master.jpg`, `02-assets/characters/patrol/master.jpg`, `02-assets/characters/siamese-rider/master.jpg` |  | 可派 |
| SH011 | i2v_first→i2v | 10 | `04-frames/SH011.jpg` | `—` | `02-assets/characters/sokha-wet/master.jpg`, `02-assets/characters/sokha-wet/face.jpg`, `02-assets/characters/yunlong/master.jpg`, `02-assets/characters/yunlong/face.jpg` |  | 可派 |
| SH012 | flf2v→flf | 6 | `04-frames/SH012.jpg` | `04-frames/SH012-last.jpg` | `02-assets/characters/sokha-wet/master.jpg`, `02-assets/characters/sokha-wet/face.jpg`, `02-assets/characters/yunlong/master.jpg`, `02-assets/characters/yunlong/face.jpg` |  | 可派 |
| SH013 | i2v_first→i2v | 7 | `04-frames/SH013.jpg` | `—` | `02-assets/characters/sokha-wet/master.jpg`, `02-assets/characters/yunlong/master.jpg`, `02-assets/characters/siamese-rider/master.jpg` | 是 | 可派 |
| SH014 | flf2v→flf | 8 | `04-frames/SH014.jpg` | `04-frames/SH014-last.jpg` | `02-assets/characters/sokha-wet/master.jpg`, `02-assets/characters/sokha-wet/face.jpg`, `02-assets/characters/yunlong/master.jpg`, `02-assets/characters/yunlong/face.jpg` |  | 可派 |
| SH015 | video_extend→i2v | 5 | `04-frames/SH015.jpg` | `—` | `02-assets/characters/sokha-wet/master.jpg` |  | 可派 |
| SH016 | flf2v→flf | 6 | `04-frames/SH016.jpg` | `04-frames/SH016-last.jpg` | `02-assets/characters/sokha-wet/master.jpg` |  | 可派 |
| SH017 | flf2v→flf | 7 | `04-frames/SH017.jpg` | `04-frames/SH017-last.jpg` | `02-assets/characters/sokha-wet/master.jpg`, `02-assets/characters/guard/master.jpg` |  | 可派 |
| SH018 | flf2v→flf | 6 | `04-frames/SH018.jpg` | `04-frames/SH018-last.jpg` | `02-assets/characters/sokha-wet/master.jpg`, `02-assets/characters/sokha-wet/face.jpg`, `02-assets/characters/guard/master.jpg`, `02-assets/characters/guard/face.jpg` |  | 可派 |
| SH019 | i2v_first→i2v | 5 | `04-frames/SH019.jpg` | `—` | — | 是 | 已有 mp4，将跳过 |
| SH020 | i2v_first→i2v | 4 | `04-frames/SH020.jpg` | `—` | `02-assets/characters/sokha-wet/master.jpg`, `02-assets/characters/sokha-wet/face.jpg` |  | 可派 |
| SH021 | flf2v→flf | 10 | `04-frames/SH021.jpg` | `04-frames/SH021-last.jpg` | `02-assets/characters/sokha-wet/master.jpg`, `02-assets/characters/sokha-wet/face.jpg` |  | 可派 |

建议顺序：先 SH001 看脸和左右轴，再最难三镜 SH004 / SH013 / SH019，不要一次派 21 镜。
flf 镜只交首尾帧：Ark 拒 last_frame 和 reference_image 混用。身份参考只给 i2v 镜。
