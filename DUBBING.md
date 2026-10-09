# Gate F · 高棉语配音 / 字幕

这部 AI 短剧和真人剧配音仓分开。那边吃「有中文人声的成片 + 无说话人的 SRT」。这边说话人已经写在 `07-dubbing/*.cues.json`。

## 两条轨

| 轨 | 声从哪来 | 关 |
|---|---|---|
| 中文工作轨 | Seedance 原声唇同步（生成包 `speech_mode=seedance_native`）。声音岗只降噪、统一音色、放进空间；原声缺 / 错词 / H3 fallback 镜才按 `voice_card` 重录该句 | E+ |
| 高棉语成片轨 | 配音 + 字幕。Seedance **没有高棉语**，`reference_audio` 又和硬首帧互斥，所以高棉语不进生成，走本页 | F |

高棉语 SRT 的时间以后按**成片音轨**（Seedance 原声的开口点）重对，不再按纸面秒 +0.6s 估。H3 / Hailuo 镜没有原声，仍按画面动作对。

## 高棉语从哪来（2026-10-08 起）

- **台词**：台词关（Gate L）锁定的 `.pipeline/lines.json`（第 N 集 `lines.epNN.json`）。Gemini 经 `agy` 按说话人、听话人、语体写的口语高棉语，人审过。本页不再翻译，`cues.json` 的 `text_km` 原样抄台词表。
- **声音**：本地克隆模型 VoxCPM2（GGUF：`VoxCPM2-BaseLM-Q8_0.gguf` + `VoxCPM2-Acoustic-F16.gguf`，Mac Metal，执行程序 `voxcpm2-cli`；调用脚本在 `高棉配音-漫剧/tools/run_voxcpm2_gguf_clone.py`）。参考声取自**该角色自己的 Seedance 中文原声**，克隆出高棉语。不用通用 TTS 朗读：机械味太重。2026-10-08 模型文件不在本机，需要时重装（`高棉配音真人剧/jobs/bysdxjx/logs/install_voxcpm2.sh`）。
- **每个角色一段固定参考声**：从 Demucs 分离出的人声里剪，只剪这个人、不跨到别人的句子；人听过再锁，整部剧这个角色所有台词都用这一段。每句拿本镜原声去克隆，会把 Seedance 各镜之间的音色差别带进高棉语。
- **每句台词都有中文原声**：电话里的声音、画外喊、旁白、内心独白，生成视频时都让模型用中文读出来（`dialogue_delivery` = phone / off_camera / narration / inner，画里的人嘴闭着）。2026-10-09 在 012 上测过：电话（SH006）和内心独白（SH031）都读出来了，画里的人嘴没动。中文读错几个字没关系：克隆按高棉语台词念，只借中文原声的音色。背景里的人喊话混在主角的喘叫里（SH012）取不出干净声音，所以一镜只许一个人出声。
- **数字**：要念的高棉语里不许有数字（克隆模型会读错），台词关已经让 Gemini 写成读法。
- **语言参数**：GGUF 版 `voxcpm2-cli` 曾经收不到 `language_id`（`高棉配音-漫剧/docs/诊断报告_同角色音色不一致_身份锁定方案.md`），发音不对时先查这一条，成片可改用 BF16 版。
- **时长**：台词关按实测语速估算高棉语秒数（`shot_table.KM_LETTERS_PER_SEC`，用《雨夜金莲》真实克隆配音校准）。克隆模型可用后，用临时参考声把整集试配一遍、量实际秒数，再回填台词表（`timing_source=measured`）。

## 人物名片

人物第一次出场时叠的两行字（名字 · 身份），和高棉语字幕一样在这一关叠，不画进画面。文字来自台词关（剧本 `captions` 里 `kind=intro` 的那几张，Gemini 写的高棉文，人审过）；落在哪一镜、哪一侧、停几秒来自分镜表的 `name_card`；时间点按剪辑时间线（`cut.json`）算。字用 Core Text 按真实高棉字体排版（`scripts/khmer_coretext.swift`），淡入淡出各 0.25 秒。

```bash
# 出视频前：在首帧上看样张
python3 scripts/render_name_cards.py --prod productions/012-khleang-moeung --episode 1 --preview
# 剪辑后：叠到成片上
python3 scripts/render_name_cards.py --prod productions/012-khleang-moeung --episode 1 --video 06-export/ep01.mp4 --out 06-export/ep01.cards.mp4
```

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

不做：为了配音拉长已经出好的画面（时长在台词关、分镜关就按高棉语排好了）；给没锁的参考声克隆成片。

旧剧（2026-10-08 以前）的高棉音色来自 `voices.json` anchor，不从中文原声克隆；新剧按上面「高棉语从哪来」。

## 声音库

跨剧复用，不绑死《雨夜金莲》：

```bash
/Users/tony/Documents/高棉配音真人剧/.venv/bin/python \
  scripts/build_khmer_voice_library.py
```
