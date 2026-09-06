# 第 01 集配音合同

画面无声。说话人写在分镜和本目录，不要再对人声做分离。

改台词只改 `ep01.cues.json`，然后：

```bash
python3 scripts/export_dub_cues.py
python3 scripts/dub_silent_episode.py --prod productions/004-yuye-jinlian --dry-run
```

画面齐了再真正贴轨，见仓库根目录 `DUBBING.md`。
