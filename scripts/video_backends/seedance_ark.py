"""Volcengine Ark Seedance 2.0 Mini (cloud image-to-video).

Create-task API: POST {base}/contents/generations/tasks
Query: GET {base}/contents/generations/tasks/{id}

Cloud backend, not a local GPU. The director desk still sends one shot at a
time: locked first frame, optional designed last frame, optional identity
refs hanging outside the first frame. Text-to-video is not a finish path.
"""
from __future__ import annotations

import base64
import mimetypes
import os
import time
from pathlib import Path
import json
from typing import Optional

import requests


def _aspect_of(image: Path) -> str:
    try:
        from PIL import Image

        with Image.open(image) as im:
            w, h = im.size
        return "16:9" if w >= h else "9:16"
    except Exception:
        return "16:9"


def _truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


FACE_BLOCK_CODE = "InputImageSensitiveContentDetected.PrivacyInformation"


class SeedanceFaceBlock(RuntimeError):
    """First-frame real-person privacy block. Official path may fall back to MiniMax-H3."""

    def __init__(self, code: str = FACE_BLOCK_CODE, body: dict | str | None = None) -> None:
        self.code = code or FACE_BLOCK_CODE
        self.body = body if body is not None else {}
        super().__init__(f"Seedance face-block: {self.code}")


def ark_error_code(body: dict | str) -> str:
    text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    parsed: dict | str = body
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    err = parsed.get("error")
    if isinstance(err, dict):
        code = str(err.get("code") or "").strip()
        if code:
            return code
    if FACE_BLOCK_CODE in text:
        return FACE_BLOCK_CODE
    return ""


def classify_create(http_status: int, body: dict | str) -> tuple[str, str, int]:
    """Return (PASS|FAIL|ERROR, raw_code, exit_code). FAIL = face-block only."""
    code = ark_error_code(body)
    if http_status < 400:
        return "PASS", code or "ok", 0
    if code == FACE_BLOCK_CODE or code.endswith(".PrivacyInformation"):
        return "FAIL", code or FACE_BLOCK_CODE, 1
    return "ERROR", code or f"HTTP_{http_status}", 2


class SeedanceArk:
    def __init__(self) -> None:
        self.api_key = os.environ.get("ARK_API_KEY", "").strip()
        if not self.api_key:
            raise SystemExit("set ARK_API_KEY to the Volcengine Ark key")
        self.base = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
        self.model = os.environ.get("ARK_SEEDANCE_MODEL", "doubao-seedance-2-0-mini-260615").strip()
        # Official 出片 is Mini 720p (1280×720). Face-block probe still forces 480p.
        self.resolution = os.environ.get("ARK_RESOLUTION", "720p").strip() or "720p"
        self.poll = int(os.environ.get("ARK_POLL_SECONDS", "8"))
        self.min_duration = int(os.environ.get("ARK_MIN_DURATION", "4"))
        self.max_duration = int(os.environ.get("ARK_MAX_DURATION", "15"))
        self.generate_audio = _truthy("ARK_GENERATE_AUDIO", "1")
        self.watermark = _truthy("ARK_WATERMARK", "0")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
        }

    def _data_url(self, image: Path) -> str:
        mime = mimetypes.guess_type(image.name)[0] or "image/jpeg"
        b64 = base64.b64encode(image.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{b64}"

    def clamp_duration(self, seconds: int, shot_id: str = "") -> int:
        """Validate, never clamp. Seconds outside the model's range are a shot-table bug to fix upstream."""
        try:
            value = int(seconds or 0)
        except (TypeError, ValueError):
            value = 0
        if value < self.min_duration or value > self.max_duration:
            where = f"{shot_id} " if shot_id else ""
            raise RuntimeError(
                f"{where}秒数 {value} 不在 {self.model} 档内 [{self.min_duration},{self.max_duration}]，改分镜表，不替人改"
            )
        return value

    def _image_item(self, image: Path, role: str | None = None) -> dict:
        item = {
            "type": "image_url",
            "image_url": {"url": self._data_url(image)},
        }
        if role:
            item["role"] = role
        return item

    def _ticket_path(self, dest: Path) -> Path:
        return dest.with_suffix(dest.suffix + ".ark-task.json")

    def _read_ticket(self, dest: Path) -> dict:
        path = self._ticket_path(dest)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_ticket(self, dest: Path, payload: dict) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        body = dict(payload)
        body["updated_at"] = int(time.time())
        self._ticket_path(dest).write_text(json.dumps(body, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")

    def build_payload(
        self,
        image: Path,
        prompt: str,
        seconds: int,
        refs: list[Path] | None = None,
        mode: str = "i2v",
        last_frame: Path | None = None,
        ratio: str | None = None,
        generate_audio: bool | None = None,
    ) -> dict:
        duration = self.clamp_duration(seconds)
        content = [
            {"type": "text", "text": prompt},
            self._image_item(image, "first_frame"),
        ]
        use_last = mode == "flf" and last_frame is not None and last_frame.exists()
        if use_last:
            content.append(self._image_item(last_frame, "last_frame"))
            # Seedance rejects last_frame mixed with reference_image.
        else:
            for ref in (refs or [])[:7]:
                if ref.resolve() == image.resolve():
                    continue
                content.append(self._image_item(ref, "reference_image"))
        return {
            "model": self.model,
            "content": content,
            "duration": duration,
            "ratio": ratio or _aspect_of(image),
            "resolution": self.resolution,
            "watermark": self.watermark,
            "generate_audio": self.generate_audio if generate_audio is None else bool(generate_audio),
            "return_last_frame": True,
        }

    def submit(
        self,
        image: Path,
        prompt: str,
        seconds: int,
        refs: list[Path] | None = None,
        mode: str = "i2v",
        last_frame: Path | None = None,
        idempotency_key: str | None = None,
        generate_audio: bool | None = None,
    ) -> str:
        if mode == "t2v":
            raise RuntimeError("Seedance 成片路径不能走文生视频")
        payload = self.build_payload(
            image, prompt, seconds, refs=refs, mode=mode, last_frame=last_frame, generate_audio=generate_audio
        )
        headers = self._headers()
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        print(f"  posting create-task timeout=300s", flush=True)
        response = requests.post(
            f"{self.base}/contents/generations/tasks",
            headers=headers,
            json=payload,
            timeout=300,
        )
        body = self._json_body(response)
        verdict, code, _exit = classify_create(response.status_code, body or response.text)
        if verdict == "FAIL":
            raise SeedanceFaceBlock(code, body or response.text)
        if response.status_code >= 400:
            raise RuntimeError(f"Ark {response.status_code}: {response.text[:500]}")
        task_id = body.get("id") or (body.get("data") or {}).get("id") or body.get("task_id")
        if not task_id:
            raise RuntimeError("Ark 没有返回任务 id: " + str(body)[:400])
        return str(task_id)

    def _json_body(self, response: requests.Response) -> dict:
        if not (response.text or "").strip():
            return {}
        try:
            body = response.json()
        except ValueError:
            return {"error": {"code": "InvalidJSON", "message": (response.text or "")[:400]}}
        return body if isinstance(body, dict) else {"error": {"code": "InvalidJSON", "message": str(body)[:400]}}

    def create_task(self, payload: dict, timeout: int = 300) -> tuple[int, dict]:
        """POST create. Returns (http_status, json) and does not raise on 400."""
        response = requests.post(
            f"{self.base}/contents/generations/tasks",
            headers=self._headers(),
            json=payload,
            timeout=timeout,
        )
        return response.status_code, self._json_body(response)

    def query_task(self, task_id: str) -> tuple[int, dict]:
        response = requests.get(
            f"{self.base}/contents/generations/tasks/{task_id}",
            headers=self._headers(),
            timeout=60,
        )
        return response.status_code, self._json_body(response)

    def cancel_task(self, task_id: str) -> tuple[int, dict]:
        """DELETE: queued → cancelled; running is not cancellable; finished records are deleted."""
        response = requests.delete(
            f"{self.base}/contents/generations/tasks/{task_id}",
            headers=self._headers(),
            timeout=60,
        )
        return response.status_code, self._json_body(response)

    def wait_url(self, task_id: str) -> str:
        url = f"{self.base}/contents/generations/tasks/{task_id}"
        while True:
            time.sleep(self.poll)
            response = requests.get(url, headers=self._headers(), timeout=60)
            if response.status_code >= 400:
                raise RuntimeError(f"Ark query {response.status_code}: {response.text[:400]}")
            body = response.json()
            status = (body.get("status") or (body.get("data") or {}).get("status") or "").lower()
            print(f"  {task_id} {status}")
            if status in {"succeeded", "success", "completed"}:
                content = body.get("content") or (body.get("data") or {}).get("content") or {}
                video = content.get("video_url") or content.get("url") or body.get("video_url")
                if not video:
                    raise RuntimeError("成功但没有视频地址: " + str(body)[:400])
                return video
            if status in {"failed", "error", "cancelled", "canceled"}:
                err = body.get("error") or (body.get("data") or {}).get("error") or body
                raise RuntimeError(f"{task_id} 失败: {err}")

    def download(self, url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(url, timeout=600)
        response.raise_for_status()
        dest.write_bytes(response.content)

    def render(
        self,
        image: Path,
        prompt: str,
        seconds: int,
        dest: Path,
        refs: list[Path] | None = None,
        mode: str = "i2v",
        last_frame: Path | None = None,
        force: bool = False,
        generate_audio: bool | None = None,
    ) -> None:
        dropped = mode == "flf" and last_frame is not None and last_frame.exists() and bool(refs)
        print(
            f"seedance {dest.name} ({seconds}s) mode={mode} refs={0 if dropped else len(refs or [])}"
            + (" (dropped: flf cannot mix last_frame with reference_image)" if dropped else ""),
            flush=True,
        )
        if not force and dest.exists() and dest.stat().st_size > 1024:
            print(f"  skip existing {dest}", flush=True)
            return
        ticket = {} if force else self._read_ticket(dest)
        task_id = "" if force else str(ticket.get("task_id") or "").strip()
        if not task_id:
            self.clamp_duration(seconds, shot_id=dest.stem)
            key = dest.resolve().as_posix()
            # A leftover "submitting" ticket never stored a task id. Reusing the
            # dest path as Idempotency-Key can replay an old Ark success.
            # --force also needs a new key, or Ark returns the old clip.
            if force or str(ticket.get("status") or "") == "submitting":
                key = f"{key}:{int(time.time())}"
            self._write_ticket(dest, {"status": "submitting", "idempotency_key": key, "dest": str(dest)})
            task_id = self.submit(
                image,
                prompt,
                seconds,
                refs=refs,
                mode=mode,
                last_frame=last_frame,
                idempotency_key=key,
                generate_audio=generate_audio,
            )
            self._write_ticket(dest, {"task_id": task_id, "status": "submitted", "idempotency_key": key, "dest": str(dest)})
            print(f"  task {task_id}", flush=True)
        else:
            print(f"  resume {task_id}", flush=True)
        url = self.wait_url(task_id)
        self._write_ticket(dest, {"task_id": task_id, "status": "succeeded", "url": url, "dest": str(dest)})
        self.download(url, dest)
        print(f"  wrote {dest}", flush=True)
