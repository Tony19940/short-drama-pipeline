# 硬约束（导演台分层加载，不要整库塞进一次 prompt）

- 文件真相只在 `productions/`。Agent 只写 `*.draft.*`，人点接受并锁定才进正式文件。
- 上游正式文件指纹变了，下游标 stale，禁止未重审出片。
- 新 Gate 0 是 `01-bible/source/`，反推仍藏在 `00-reverse/`，两套不要撞车。
- `check_prod.py` 不过关不准出视频。
- 主路径锁定首帧 FL2VA。`end_frame` 不能是 `-last.jpg`。Ref2VA 未安装就停，不冒充。
