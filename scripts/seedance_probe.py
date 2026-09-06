#!/usr/bin/env python3
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from director.paths import load_dotenv
from video_backends.seedance_ark import SeedanceArk
load_dotenv()
image = ROOT / "productions/009-siem-reap/.pipeline/seedance-probe/probe-first-480p.jpg"
dest = ROOT / "productions/009-siem-reap/.pipeline/seedance-probe/probe-480p.mp4"
log = ROOT / "productions/009-siem-reap/.pipeline/seedance-probe/probe.log"
def w(msg):
    with log.open("a", encoding="utf-8") as handle:
        handle.write(msg + chr(10))
        handle.flush()
    print(msg, flush=True)
def main():
    log.write_text("", encoding="utf-8")
    w("start")
    backend = SeedanceArk()
    w("model=" + backend.model)
    w("resolution=" + backend.resolution)
    w("base=" + backend.base)
    w("key_len=" + str(len(backend.api_key)))
    prompt = "16:9 横屏，固定机位。一个高棉河边的人站在石槽前，手微微动一下，不要说话，不要字幕，不要水印。"
    backend.render(image, prompt, 4, dest, refs=[], mode="i2v")
    w("bytes=" + str(dest.stat().st_size))
    w("DONE")
if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        w("ERROR " + type(exc).__name__ + ": " + str(exc)[:800])
        raise
