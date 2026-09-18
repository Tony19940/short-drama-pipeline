# Gate F · 高棉语配音 / 字幕

这部 AI 短剧和真人剧配音仓分开。那边吃「有中文人声的成片 + 无说话人的 SRT」。这边说话人已经写在 `07-dubbing/*.cues.json`。

## 两条轨

| 轨 | 声从哪来 | 关 |
|---|---|---|
| 中文工作轨 | Seedance 原声唇同步（生成包 `speech_mode=seedance_native`）。声音岗只降噪、统一音色、放进空间；原声缺 / 错词 / H3 fallback 镜才按 `voice_card` 重录该句 | E+ |
| 高棉语成片轨 | 配音 + 字幕。Seedance **没有高棉语**，`reference_audio` 又和硬首帧互斥，所以高棉语不进生成，走本页 | F |

高棉语 SRT 的时间以后按**成片音轨**（Seedance 原声的开口点）重对，不再按纸面秒 +0.6s 估。H3 / Hailuo 镜没有原声，仍按画面动作对。

## 顺序

1. 单镜齐了，先按分镜表混音效床（E+，只出 SFX，不对白、不 BGM）：

```bash
python3 scripts/mix_episode_sfx.py --prod productions/009-siem-reap --dry-run
python3 scripts/mix_episode_sfx.py --prod productions/009-siem-reap
```

写出 `07-dubbing/sfx/ep01-sfx.m4a`。合同是锁定表上的 `key_sfx[]`。人听过预览再锁。
2. 再拼 `06-export/ep01.mp4`（中文原声 + 音效，或只带音效）。
3. 最后贴高棉语对白 / 字幕。云端出片只要中文原声对白和环境声；BGM、高棉语、字幕都在这一步后期加，不写进提示词。

```bash
python3 scripts/dub_silent_episode.py \
  --prod productions/004-yuye-jinlian \
  --dry-run

# 画面齐了、克隆服务也在，再真正贴：
python3 scripts/dub_silent_episode.py --prod productions/004-yuye-jinlian
```

## 吃什么

| 文件 | 用途 |
|---|---|
| `07-dubbing/sfx/ep01-sfx.m4a` | 整集音效床（先混这个） |
| `07-dubbing/ep01.cues.json` | 说话人、时间、高棉语 |
| `07-dubbing/voices.json` | 角色 → `shared/khmer-voices/` 里的 anchor |
| `06-export/ep01.mp4` | 中文原声 + 音效的画面（高棉版替换对白轨），或只带音效 |
| `KHMER_CLONE_CLOUD_URL` | 和其他配音项目同一套克隆服务 |

不做：说话人分离、抽原片人声（高棉音色来自 `voices.json` anchor，不从中文原声克隆）、为了配音拉长 64 秒画面。

## 声音库

跨剧复用，不绑死《雨夜金莲》：

```bash
/Users/tony/Documents/高棉配音真人剧/.venv/bin/python \
  scripts/build_khmer_voice_library.py
```
