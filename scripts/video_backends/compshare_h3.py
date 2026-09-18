"""CompShare ModelVerse MiniMax-H3 (async video tasks).

Docs: https://www.compshare.cn/docs/modelverse/models/video_api/minimax-h3-video-api
Host: https://cp.compshare.cn  Key prefix: sk-ml-

Platform rules that differ from official MiniMax:
- resolution is 768P only
- first_frame cannot be mixed with reference_image / video / audio
- image_url must be a URL their China-side fetcher can download (no data URLs)
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests


class CompShareH3:
    MIN_DURATION = 4
    MAX_DURATION = 15

    def __init__(self) -> None:
        self.api_key = os.environ.get("COMPSHARE_API_KEY", "").strip()
        if not self.api_key:
            raise SystemExit("set COMPSHARE_API_KEY")
        self.base = os.environ.get("COMPSHARE_BASE_URL", "https://cp.compshare.cn").rstrip("/")
        self.model = os.environ.get("COMPSHARE_MODEL", "MiniMax-H3")
        self.resolution = os.environ.get("COMPSHARE_RESOLUTION", "768P")
        self.ratio = os.environ.get("COMPSHARE_RATIO", "16:9")
        self.poll = int(os.environ.get("COMPSHARE_POLL_SECONDS", "12"))

    def _headers(self, idempotency: str | None = None) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if idempotency:
            h["Idempotency-Key"] = idempotency
        return h

    def _jsdelivr_url(self, image: Path) -> str:
        """CompShare's fetcher can pull cdn.jsdelivr.net; most other hosts RST."""
        repo = os.environ.get("COMPSHARE_IMAGE_REPO", "Tony19940/compshare-h3-tmp").strip()
        blob = image.read_bytes()
        digest = hashlib.sha1(blob).hexdigest()[:12]
        path = f"{image.stem}-{digest}{image.suffix.lower() or '.jpg'}"
        b64 = base64.b64encode(blob).decode("ascii")
        print(f"  uploading first frame to GitHub {repo}/{path} ...", flush=True)
        existing = subprocess.run(
            ["gh", "api", f"/repos/{repo}/contents/{path}"],
            capture_output=True,
            text=True,
        )
        payload: dict[str, str] = {
            "message": f"compshare first frame {path}",
            "content": b64,
        }
        if existing.returncode == 0:
            sha = json.loads(existing.stdout).get("sha")
            if sha:
                payload["sha"] = sha
        put = subprocess.run(
            ["gh", "api", "-X", "PUT", f"/repos/{repo}/contents/{path}", "--input", "-"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )
        if put.returncode != 0:
            raise RuntimeError(put.stderr.strip() or put.stdout.strip() or "gh api put failed")
        json.loads(put.stdout)
        # @main is fetchable from CompShare; short commit hashes redirect to githubusercontent and RST.
        url = f"https://cdn.jsdmirror.cn/gh/{repo}@main/{path}"
        print(f"  jsdelivr -> {url}", flush=True)
        time.sleep(2)
        return url

    def _host_urls(self, image: Path):
        extra = os.environ.get("COMPSHARE_IMAGE_URL", "").strip()
        if extra:
            yield extra
        try:
            yield self._jsdelivr_url(image)
        except Exception as e:
            print(f"  github/jsdelivr skipped: {e}", flush=True)
        mime = mimetypes.guess_type(image.name)[0] or "image/jpeg"
        blob = image.read_bytes()
        try:
            print("  uploading first frame via catbox ...", flush=True)
            got = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": (image.name, blob, mime)},
                timeout=30,
            ).text.strip()
            if got.startswith("http"):
                print(f"  catbox -> {got}", flush=True)
                yield got
        except Exception as e:
            print(f"  catbox skipped: {e}", flush=True)

    def points(self) -> dict:
        r = requests.get(
            f"{self.base}/minimax/v2/query/point_usage_summary",
            headers=self._headers(),
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def clamp_duration(self, seconds: int, shot_id: str = "") -> int:
        """Validate, never clamp. H3 takes 4–15 s; anything else is a shot-table bug to fix upstream."""
        try:
            value = int(seconds or 0)
        except (TypeError, ValueError):
            value = 0
        if value < self.MIN_DURATION or value > self.MAX_DURATION:
            where = f"{shot_id} " if shot_id else ""
            raise RuntimeError(
                f"{where}秒数 {value} 不在 {self.model} 档内 [{self.MIN_DURATION},{self.MAX_DURATION}]，改分镜表，不替人改"
            )
        return value

    def _create(self, prompt: str, seconds: int, image_url: str) -> requests.Response:
        payload = {
            "model": self.model,
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": image_url},
                    "role": "first_frame",
                },
            ],
            "resolution": self.resolution,
            "duration": self.clamp_duration(seconds),
            "ratio": self.ratio,
            "use_context_ir": False,
            "aigc_watermark": False,
        }
        print(f"  posting create task with {image_url[:80]}...", flush=True)
        return requests.post(
            f"{self.base}/minimax/v2/video_generation",
            headers=self._headers(idempotency=str(uuid.uuid4())),
            json=payload,
            timeout=120,
        )

    def submit(self, image: Path, prompt: str, seconds: int, refs: list[Path] | None = None) -> str:
        if refs:
            print("  compshare: dropping reference_image (cannot mix with first_frame)", flush=True)
        locked = (
            "Keep the exact faces, bodies, wardrobe, and jewelry from the first-frame image. "
            "Do not change identity. No spoken dialogue. Ambient sound only. "
        )
        last_err = ""
        for image_url in self._host_urls(image):
            r = self._create(locked + prompt, seconds, image_url)
            if r.status_code < 400:
                body = r.json()
                task_id = body.get("task_id") or body.get("task", {}).get("id")
                if not task_id:
                    last_err = f"no task_id in {body}"
                    continue
                return str(task_id)
            last_err = f"{r.status_code}: {r.text[:800]}"
            print(f"  host rejected ({last_err[:180]})", flush=True)
            if "download image" not in (r.text or "").lower() and "Get " not in (r.text or ""):
                break
        raise RuntimeError(f"create task failed: {last_err}")

    def wait_url(self, task_id: str) -> str:
        url = f"{self.base}/minimax/v2/query/video_generation/{task_id}"
        while True:
            time.sleep(self.poll)
            try:
                r = requests.get(url, headers=self._headers(), timeout=60)
                r.raise_for_status()
            except requests.RequestException as e:
                print(f"  poll retry: {e}", flush=True)
                continue
            task = r.json().get("task") or r.json()
            status = task.get("status")
            print(f"  {task_id} {status}", flush=True)
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
        self.clamp_duration(seconds, shot_id=dest.stem)
        pts = self.points()
        print(
            f"compshare h3 {dest.name} ({seconds}s) 768P "
            f"points available={pts.get('available_points')} reserved={pts.get('reserved_points')}",
            flush=True,
        )
        task_id = self.submit(image, prompt, seconds, refs)
        print(f"  task {task_id}", flush=True)
        url = self.wait_url(task_id)
        self.download(url, dest)
        print(f"  wrote {dest}", flush=True)


if __name__ == "__main__":
    client = CompShareH3()
    if "--balance" in sys.argv:
        print(client.points())
        raise SystemExit(0)
    raise SystemExit("usage: python3 scripts/video_backends/compshare_h3.py --balance")
