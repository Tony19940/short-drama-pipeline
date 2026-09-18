# 音效床（E+，画面之后）

单镜视频齐了再混。合同是锁定分镜表的 `key_sfx[]`，不是现搜现编。

```bash
python3 scripts/mix_episode_sfx.py --prod productions/<slug> --dry-run
python3 scripts/mix_episode_sfx.py --prod productions/<slug>
```

- 文件：`07-dubbing/sfx/epXX-sfx.m4a`
- 时长跟 `05-shots/*.mp4` 真拼接走，不跟纸面秒数
- 只出 SFX，不对白、不 BGM
- Seedance / 云端自带声不当成品
- 有 `07-dubbing/sfx/overrides.json` 时按已审时间轴，不再按标签重排
- 工厂/现代工业标签（车轮、钥匙、柜门、扫把、工牌口袋等）走 `sfx.py` 的 factory 规则；古代战争标签保持原映射
