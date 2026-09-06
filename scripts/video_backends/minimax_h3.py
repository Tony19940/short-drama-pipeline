"""MiniMax-H3 official API (v2). First-frame image-to-video."""

from __future__ import annotations

import base64
import mimetypes
import os
import time
from pathlib import Path

import requests


class MiniMaxH3:
    def __init__(self) -> None:
        self.api_key = os.environ.get("MINIMAX_API_KEY", "").strip()
        if not self.api_key:
            raise SystemExit("set MINIMAX_API_KEY")
        self.base = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io").rstrip("/")
        self.model = os.environ.get("MINIMAX_MODEL", "MiniMax-H3")
        self.resolution = os.environ.get("MINIMAX_RESOLUTION", "768P")
        self.poll = int(os.environ.get("MINIMAX_POLL_SECONDS", "12"))

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _data_url(self, image: Path) -> str:
        mime = mimetypes.guess_type(image.name)[0] or "image/jpeg"
        b64 = base64.b64encode(image.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{b64}"

    def submit(self, image: Path, prompt: str, seconds: int, refs: list[Path] | None = None) -> str:
        locked = (
            "Keep the exact faces, bodies, wardrobe, and jewelry from the reference images. "
            "Do not change identity. No spoken dialogue. Ambient sound only. "
        )
        content: list[dict] = [
            {"type": "text", "text": locked + prompt},
            {
                "type": "image_url",
                "image_url": {"url": self._data_url(image)},
                "role": "first_frame",
            },
        ]
        for ref in (refs or [])[:4]:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self._data_url(ref)},
                    "role": "reference_image",
                }
            )
        payload = {
            "model": self.model,
            "duration": max(4, min(15, int(seconds))),
            "resolution": self.resolution,
            "content": content,
        }
        r = requests.post(
            f"{self.base}/v2/video_generation",
            headers=self._headers(),
            json=payload,
            timeout=120,
        )
        r.raise_for_status()
        body = r.json()
        task_id = body.get("task_id") or body.get("task", {}).get("id")
        if not task_id:
            raise RuntimeError(f"no task_id in {body}")
        return str(task_id)

    def wait_url(self, task_id: str) -> str:
        url = f"{self.base}/v2/query/video_generation/{task_id}"
        while True:
            time.sleep(self.poll)
            r = requests.get(url, headers=self._headers(), timeout=60)
            r.raise_for_status()
            task = r.json().get("task") or r.json()
            status = task.get("status")
            print(f"  {task_id} {status}")
            if status in ("succeeded", "success"):
                content = task.get("content") or {}
                download = content.get("url")
                if not download:
                    raise RuntimeError(f"succeeded but no url: {task}")
                return download
            if status in ("failed", "cancelled"):
                raise RuntimeError(f"{task_id} {status}: {task.get('error')}")

    def download(self, url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(url, timeout=180)
        r.raise_for_status()
        dest.write_bytes(r.content)

    def render(
        self,
        image: Path,
        prompt: str,
        seconds: int,
        dest: Path,
        refs: list[Path] | None = None,
    ) -> None:
        print(f"h3 {dest.name} ({seconds}s) refs={len(refs or [])}")
        task_id = self.submit(image, prompt, seconds, refs)
        print(f"  task {task_id}")
        url = self.wait_url(task_id)
        self.download(url, dest)
        print(f"  wrote {dest}")
