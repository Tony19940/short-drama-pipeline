"""Volcengine Ark Seedance 2.0 Mini (cloud image-to-video).

Create-task API: POST {base}/contents/generations/tasks
Query: GET {base}/contents/generations/tasks/{id}

Cloud backend, not a local GPU. The director desk still sends one shot at a
time: locked first frame, optional designed last frame, optional identity
refs hanging outside the first frame. Text-to-video is not a finish path.
"""
from __future__ import annotations

import base64
import hashlib
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


def looks_like_mp4_file(path: Path) -> bool:
    dest = Path(path)
    if not dest.is_file() or dest.stat().st_size <= 1024:
        return False
    head = dest.read_bytes()[:32]
    return b"ftyp" in head


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
    def __init__(
        self,
        *,
        model: str | None = None,
        resolution: str | None = None,
        min_duration: int | None = None,
        max_duration: int | None = None,
        generate_audio: bool | None = None,
    ) -> None:
        self.api_key = os.environ.get("ARK_API_KEY", "").strip()
        if not self.api_key:
            raise SystemExit("set ARK_API_KEY to the Volcengine Ark key")
        self.base = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
        # Confirmed request fields win. Env is only the unconfirmed default.
        self.model = (model or os.environ.get("ARK_SEEDANCE_MODEL") or "doubao-seedance-2-0-mini-260615").strip()
        # Official 出片 is Mini 720p (1280×720). Face-block probe still forces 480p.
        self.resolution = (resolution or os.environ.get("ARK_RESOLUTION") or "720p").strip() or "720p"
        self.poll = int(os.environ.get("ARK_POLL_SECONDS", "8"))
        self.min_duration = int(min_duration if min_duration is not None else os.environ.get("ARK_MIN_DURATION", "4"))
        self.max_duration = int(max_duration if max_duration is not None else os.environ.get("ARK_MAX_DURATION", "15"))
        self.generate_audio = bool(generate_audio) if generate_audio is not None else _truthy("ARK_GENERATE_AUDIO", "1")
        self.watermark = _truthy("ARK_WATERMARK", "0")

    @classmethod
    def from_request(cls, request: object) -> "SeedanceArk":
        from director.vendor_request import VendorRequest
        from director.video_profiles import get_profile

        if not isinstance(request, VendorRequest):
            raise TypeError("from_request expects VendorRequest")
        profile = get_profile(request.profile_id)
        inst = cls(
            model=request.model,
            resolution=request.resolution,
            min_duration=int(profile.get("min_shot_sec") or 4),
            max_duration=int(profile.get("max_shot_sec") or 15),
            generate_audio=request.generate_audio,
        )
        inst.watermark = bool(getattr(request, "watermark", False))
        return inst

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
        }

    def _data_url(self, image: Path) -> str:
        mime = mimetypes.guess_type(image.name)[0] or "image/jpeg"
        b64 = base64.b64encode(image.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{b64}"

    def _is_25(self) -> bool:
        return "2-5" in self.model or "2.5" in self.model

    def clamp_duration(self, seconds: int, shot_id: str = "", *, allow_minus_one: bool = False) -> int:
        """Validate, never clamp. Seconds outside the model's range are a shot-table bug to fix upstream."""
        try:
            value = int(seconds or 0)
        except (TypeError, ValueError):
            value = 0
        if allow_minus_one and value == -1:
            return -1
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

    def _video_item(self, video: Path, role: str = "reference_video") -> dict:
        return {
            "type": "video_url",
            "video_url": {"url": self._data_url(video)},
            "role": role,
        }

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
        path = self._ticket_path(dest)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
        tmp.replace(path)

    def _file_hash(self, path: Path | None) -> str:
        if path is None or not Path(path).is_file():
            return ""
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def compute_request_hash(
        self,
        image: Path,
        prompt: str,
        seconds: int,
        refs: list[Path] | None = None,
        mode: str = "i2v",
        last_frame: Path | None = None,
        generate_audio: bool | None = None,
        source_video: Path | None = None,
    ) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "seconds": int(seconds),
            "mode": mode,
            "resolution": self.resolution,
            "generate_audio": self.generate_audio if generate_audio is None else bool(generate_audio),
            "image": self._file_hash(image),
            "last_frame": self._file_hash(last_frame),
            "source_video": self._file_hash(source_video),
            "refs": [self._file_hash(ref) for ref in (refs or [])],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def looks_like_mp4(self, path: Path) -> bool:
        return looks_like_mp4_file(path)

    @staticmethod
    def clip_matches_request(dest: Path, request_hash: str) -> bool:
        if not looks_like_mp4_file(dest):
            return False
        path = dest.with_suffix(dest.suffix + ".ark-task.json")
        if not path.is_file():
            return False
        try:
            ticket = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(ticket, dict):
            return False
        stored = str(ticket.get("request_hash") or "").strip()
        if not stored or stored != str(request_hash or "").strip():
            return False
        return str(ticket.get("status") or "") in {"succeeded", "downloaded", "verified"}

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
        source_video: Path | None = None,
        watermark: bool | None = None,
    ) -> dict:
        if mode == "video_extend":
            mode = "extend"
        if mode not in {"i2v", "flf", "extend", "edit", "reference"}:
            raise RuntimeError(f"unsupported Seedance mode: {mode}")
        audio = self.generate_audio if generate_audio is None else bool(generate_audio)
        mark = self.watermark if watermark is None else bool(watermark)
        if mode in {"extend", "edit"}:
            if source_video is None or not Path(source_video).is_file():
                raise RuntimeError(f"{mode} requires reference_video")
            duration = -1 if mode == "edit" else self.clamp_duration(seconds)
            payload = {
                "model": self.model,
                "content": [
                    {"type": "text", "text": prompt},
                    self._video_item(Path(source_video), "reference_video"),
                ],
                "duration": duration,
                "ratio": ratio or "adaptive",
                "resolution": self.resolution,
                "watermark": mark,
                "generate_audio": audio,
                "return_last_frame": True,
            }
            if self._is_25():
                payload["omni_reference_task_type"] = mode
            return payload
        if mode == "reference":
            content: list[dict] = [{"type": "text", "text": prompt}]
            for ref in refs or []:
                if Path(ref).is_file():
                    content.append(self._image_item(Path(ref), "reference_image"))
            if len(content) < 2:
                raise RuntimeError("reference task needs at least one reference_image")
            payload = {
                "model": self.model,
                "content": content,
                "duration": self.clamp_duration(seconds),
                "ratio": ratio or "adaptive",
                "resolution": self.resolution,
                "watermark": mark,
                "generate_audio": audio,
                "return_last_frame": True,
            }
            if self._is_25():
                payload["omni_reference_task_type"] = "reference"
            return payload
        duration = self.clamp_duration(seconds)
        content = [
            {"type": "text", "text": prompt},
            self._image_item(image, "first_frame"),
        ]
        use_last = mode == "flf" and last_frame is not None and last_frame.exists()
        if use_last:
            content.append(self._image_item(last_frame, "last_frame"))
        elif mode == "i2v" and not self._is_25():
            for ref in (refs or [])[:7]:
                if ref.resolve() == image.resolve():
                    continue
                content.append(self._image_item(ref, "reference_image"))
        if ratio:
            submit_ratio = ratio
        elif self._is_25() and mode in {"i2v", "flf"}:
            submit_ratio = "adaptive"
        else:
            submit_ratio = _aspect_of(image)
        return {
            "model": self.model,
            "content": content,
            "duration": duration,
            "ratio": submit_ratio,
            "resolution": self.resolution,
            "watermark": mark,
            "generate_audio": audio,
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
        source_video: Path | None = None,
        ratio: str | None = None,
        watermark: bool | None = None,
    ) -> str:
        if mode == "t2v":
            raise RuntimeError("Seedance 成片路径不能走文生视频")
        payload = self.build_payload(
            image,
            prompt,
            seconds,
            refs=refs,
            mode=mode,
            last_frame=last_frame,
            generate_audio=generate_audio,
            source_video=source_video,
            ratio=ratio,
            watermark=watermark,
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
        part = dest.with_name(dest.name + ".part")
        response = requests.get(url, timeout=600)
        response.raise_for_status()
        part.write_bytes(response.content)
        if not looks_like_mp4_file(part):
            part.unlink(missing_ok=True)
            raise RuntimeError("downloaded file failed mp4 technical check")
        part.replace(dest)

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
        source_video: Path | None = None,
        request_hash: str = "",
        ratio: str | None = None,
        watermark: bool | None = None,
        submit_duration: int | None = None,
    ) -> None:
        dropped = mode == "flf" and last_frame is not None and last_frame.exists() and bool(refs)
        req_hash = request_hash or self.compute_request_hash(
            image,
            prompt,
            seconds,
            refs=refs,
            mode=mode,
            last_frame=last_frame,
            generate_audio=generate_audio,
            source_video=source_video,
        )
        print(
            f"seedance {dest.name} ({seconds}s) mode={mode} refs={0 if dropped else len(refs or [])}"
            + (" (dropped: flf cannot mix last_frame with reference_image)" if dropped else ""),
            flush=True,
        )
        ticket = {} if force else self._read_ticket(dest)
        ticket_hash = str(ticket.get("request_hash") or "")
        if not force and self.clip_matches_request(dest, req_hash):
            print(f"  skip existing {dest}", flush=True)
            return
        if not force and dest.exists() and dest.stat().st_size > 1024:
            print(f"  dest exists but request changed or clip unreadable; not skipping", flush=True)
        task_id = "" if force else str(ticket.get("task_id") or "").strip()
        if task_id and not ticket_hash:
            print("  legacy ticket has no request_hash; refusing to resume", flush=True)
            task_id = ""
        elif task_id and ticket_hash != req_hash:
            task_id = ""
        sent_seconds = seconds if submit_duration is None else submit_duration
        if not task_id:
            if mode not in {"edit"} and sent_seconds != -1:
                self.clamp_duration(seconds, shot_id=dest.stem)
            key = str(ticket.get("idempotency_key") or "")
            if force or not key or ticket_hash != req_hash:
                key = f"{dest.resolve().as_posix()}:{req_hash[:16]}"
                if force:
                    key = f"{key}:{int(time.time())}"
            self._write_ticket(
                dest,
                {"status": "submitting", "idempotency_key": key, "dest": str(dest), "request_hash": req_hash},
            )
            task_id = self.submit(
                image,
                prompt,
                sent_seconds if mode != "edit" else seconds,
                refs=refs,
                mode=mode,
                last_frame=last_frame,
                idempotency_key=key,
                generate_audio=generate_audio,
                source_video=source_video,
                ratio=ratio,
                watermark=watermark,
            )
            self._write_ticket(
                dest,
                {
                    "task_id": task_id,
                    "status": "submitted",
                    "idempotency_key": key,
                    "dest": str(dest),
                    "request_hash": req_hash,
                },
            )
            print(f"  task {task_id}", flush=True)
        else:
            print(f"  resume {task_id}", flush=True)
        url = self.wait_url(task_id)
        self._write_ticket(
            dest,
            {
                "task_id": task_id,
                "status": "remote_succeeded",
                "url": url,
                "dest": str(dest),
                "request_hash": req_hash,
            },
        )
        self.download(url, dest)
        self._write_ticket(
            dest,
            {
                "task_id": task_id,
                "status": "verified",
                "url": url,
                "dest": str(dest),
                "request_hash": req_hash,
            },
        )
        print(f"  wrote {dest}", flush=True)

    def render_request(self, request: object, dest: Path, *, prod: Path, force: bool = False) -> None:
        from director.vendor_request import VendorRequest
        from director.paths import safe_under

        if not isinstance(request, VendorRequest):
            raise TypeError("render_request expects VendorRequest")
        image = safe_under(prod, request.first_frame) if request.first_frame else dest
        last = safe_under(prod, request.last_frame) if request.last_frame else None
        source = safe_under(prod, request.source_video) if request.source_video else None
        refs = [safe_under(prod, rel) for rel in request.refs if rel]
        self.render(
            image,
            request.prompt,
            int(request.duration_sec),
            dest,
            refs=refs,
            mode=request.seedance_mode(),
            last_frame=last,
            force=force,
            generate_audio=request.generate_audio,
            source_video=source,
            request_hash=request.fingerprint(),
            ratio=request.submit_ratio or request.ratio,
            watermark=request.watermark,
            submit_duration=int(request.submit_duration_sec),
        )
