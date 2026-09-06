"""Self-hosted MiniMax H3 on a rented GPU.

Expected HTTP contract. Copy `scripts/video_backends/runpod_i2v_server.py`
onto the new box; the four-point director contract lives in this repo, not
on whatever GPU happens to be running.

POST {base}/v1/i2v
  JSON: {image_b64, prompt, duration, aspect, mode, refs_b64, last_frame_b64?}
  -> {task_id}

GET {base}/v1/i2v/{task_id}
  -> {status: queued|running|succeeded|failed, url?}

Contract:
1. image_b64 is always the locked first frame (designed still, or previous
   true last frame on same-setup continue).
2. last_frame_b64 is only a designed end still, never `{id}-last.jpg`.
3. mode=i2v|flf|r2v. r2v means FL2VA first frame PLUS identity refs hanging
   outside it. Missing fields must still work as first-frame I2V.
4. refs_b64 never replace the first frame. A new GPU without a Ref2VA UNet
   must fail loudly instead of pretending r2v ran.
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path

import requests


def _aspect_of(image: Path) -> str:
    try:
        from PIL import Image
        with Image.open(image) as im:
            w, h = im.size
        return "16:9" if w >= h else "9:16"
    except Exception:
        return "9:16"


class LocalH3:
    def __init__(self) -> None:
        self.base = os.environ.get("LOCAL_H3_BASE", "").rstrip("/")
        if not self.base:
            raise SystemExit("set LOCAL_H3_BASE to the GPU box, e.g. http://x.x.x.x:8000")
        self.poll = int(os.environ.get("LOCAL_H3_POLL_SECONDS", "8"))
        self.token = os.environ.get("LOCAL_H3_TOKEN", "").strip()

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def submit(
        self,
        image: Path,
        prompt: str,
        seconds: int,
        refs: list[Path] | None = None,
        mode: str = "i2v",
        last_frame: Path | None = None,
    ) -> str:
        payload = {
            "image_b64": base64.b64encode(image.read_bytes()).decode("ascii"),
            "prompt": prompt,
            "duration": seconds,
            "aspect": _aspect_of(image),
            "no_audio": True,
            "mode": mode,
            "refs_b64": [
                base64.b64encode(p.read_bytes()).decode("ascii") for p in (refs or [])[:4]
            ],
        }
        if last_frame and last_frame.exists():
            payload["last_frame_b64"] = base64.b64encode(last_frame.read_bytes()).decode("ascii")
        r = requests.post(f"{self.base}/v1/i2v", headers=self._headers(), json=payload, timeout=120)
        r.raise_for_status()
        body = r.json()
        task_id = body.get("task_id") or body.get("id")
        if not task_id:
            raise RuntimeError(f"no task_id in {r.text}")
        return str(task_id)

    def wait_url(self, task_id: str) -> str:
        while True:
            time.sleep(self.poll)
            r = requests.get(f"{self.base}/v1/i2v/{task_id}", headers=self._headers(), timeout=60)
            r.raise_for_status()
            body = r.json()
            status = body.get("status")
            print(f"  {task_id} {status}")
            if status in {"succeeded", "success", "ready"}:
                url = body.get("url") or body.get("video_url")
                if not url:
                    raise RuntimeError(f"succeeded but no url: {body}")
                if url.startswith("/"):
                    url = self.base + url
                return url
            if status in {"failed", "error"}:
                raise RuntimeError(f"{task_id} failed: {body.get('error')}")

    def download(self, url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if url.startswith("file://"):
            dest.write_bytes(Path(url[7:]).read_bytes())
            return
        if url.startswith("/") and Path(url).exists():
            dest.write_bytes(Path(url).read_bytes())
            return
        r = requests.get(url, headers=self._headers(), timeout=600)
        r.raise_for_status()
        dest.write_bytes(r.content)

    def render(
        self,
        image: Path,
        prompt: str,
        seconds: int,
        dest: Path,
        refs: list[Path] | None = None,
        mode: str = "i2v",
        last_frame: Path | None = None,
    ) -> None:
        print(f"local {dest.name} ({seconds}s) mode={mode} refs={len(refs or [])}")
        task_id = self.submit(image, prompt, seconds, refs, mode=mode, last_frame=last_frame)
        print(f"  task {task_id}")
        url = self.wait_url(task_id)
        self.download(url, dest)
        print(f"  wrote {dest}")
