# Gate F · 无声画面配音

这部 AI 短剧和真人剧配音仓分开。那边吃「有中文人声的成片 + 无说话人的 SRT」。这边画面是无声的，说话人已经写在 `07-dubbing/*.cues.json`。

## 顺序

1. 单镜齐了，先按分镜表混音效床（E+，只出 SFX，不对白、不 BGM）：

```bash
python3 scripts/mix_episode_sfx.py --prod productions/009-siem-reap --dry-run
python3 scripts/mix_episode_sfx.py --prod productions/009-siem-reap
```

写出 `07-dubbing/sfx/ep01-sfx.m4a`。合同是锁定表上的 `key_sfx[]`。人听过预览再锁。
2. 再拼 `06-export/ep01.mp4`（静音或只带音效）。
3. 最后贴对白 / 高棉语。不要在云端出片时赌环境声、BGM、人声。

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
| `06-export/ep01.mp4` | 无声或只带音效的画面 |
| `KHMER_CLONE_CLOUD_URL` | 和其他配音项目同一套克隆服务 |

不做：说话人分离、抽原片人声、为了配音拉长 64 秒画面。

## 声音库

跨剧复用，不绑死《雨夜金莲》：

```bash
/Users/tony/Documents/高棉配音真人剧/.venv/bin/python \
  scripts/build_khmer_voice_library.py
```
