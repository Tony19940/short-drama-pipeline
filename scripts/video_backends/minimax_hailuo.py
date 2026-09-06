"""MiniMax Hailuo 2.3 / 2.3-Fast (v1). Silent image-to-video. Default cheap path."""

from __future__ import annotations

import base64
import mimetypes
import os
import time
from pathlib import Path

import requests


class MiniMaxHailuo:
    def __init__(self) -> None:
        self.api_key = os.environ.get("MINIMAX_API_KEY", "").strip()
        if not self.api_key:
            raise SystemExit("set MINIMAX_API_KEY")
        self.base = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io").rstrip("/")
        self.model = os.environ.get("MINIMAX_FAST_MODEL", "MiniMax-Hailuo-2.3-Fast")
        self.resolution = os.environ.get("MINIMAX_FAST_RESOLUTION", "768P")
        self.poll = int(os.environ.get("MINIMAX_POLL_SECONDS", "12"))

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _data_url(self, image: Path) -> str:
        mime = mimetypes.guess_type(image.name)[0] or "image/jpeg"
        b64 = base64.b64encode(image.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{b64}"

    def submit(self, image: Path, prompt: str, seconds: int, refs: list[Path] | None = None) -> str:
        duration = 10 if seconds >= 8 else 6
        payload = {
            "model": self.model,
            "prompt": prompt,
            "first_frame_image": self._data_url(image),
            "duration": duration,
            "resolution": self.resolution,
            "prompt_optimizer": True,
        }
        r = requests.post(
            f"{self.base}/v1/video_generation",
            headers=self._headers(),
            json=payload,
            timeout=120,
        )
        r.raise_for_status()
        body = r.json()
        if body.get("base_resp", {}).get("status_code", 0) not in (0, None):
            raise RuntimeError(body)
        task_id = body.get("task_id")
        if not task_id:
            raise RuntimeError(f"no task_id in {body}")
        return str(task_id)

    def wait_url(self, task_id: str) -> str:
        query = f"{self.base}/v1/query/video_generation"
        while True:
            time.sleep(self.poll)
            r = requests.get(query, headers=self._headers(), params={"task_id": task_id}, timeout=60)
            r.raise_for_status()
            body = r.json()
            status = body.get("status") or body.get("task", {}).get("status")
            print(f"  {task_id} {status}")
            if status in ("Success", "success", "succeeded"):
                file_id = body.get("file_id")
                if file_id:
                    return self._file_url(str(file_id))
                url = (body.get("content") or {}).get("url")
                if url:
                    return url
                raise RuntimeError(f"success but no file: {body}")
            if status in ("Fail", "failed", "cancelled"):
                raise RuntimeError(f"{task_id} {status}: {body}")

    def _file_url(self, file_id: str) -> str:
        r = requests.get(
            f"{self.base}/v1/files/retrieve",
            headers=self._headers(),
            params={"file_id": file_id},
            timeout=60,
        )
        r.raise_for_status()
        body = r.json()
        url = (body.get("file") or {}).get("download_url") or body.get("download_url")
        if not url:
            raise RuntimeError(f"no download_url: {body}")
        return url

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
        print(f"hailuo {dest.name} ({seconds}s) {self.model}")
        task_id = self.submit(image, prompt, seconds, refs)
        print(f"  task {task_id}")
        url = self.wait_url(task_id)
        self.download(url, dest)
        print(f"  wrote {dest}")
