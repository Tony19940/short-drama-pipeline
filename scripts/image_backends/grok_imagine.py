"""xAI Grok Imagine stills. grok-4.6 is text-only; pixels go through this API."""

from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path
from typing import List, Optional

import requests


DEFAULT_MODEL = "grok-imagine-image-2.0"
DEFAULT_BASE = "https://api.x.ai/v1"


class ImagineError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict:
        return {"code": self.code, "error": self.message}


class GrokImagine:
    def __init__(self) -> None:
        self.api_key = os.environ.get("XAI_API_KEY", "").strip()
        if not self.api_key:
            raise ImagineError(
                "NEED_XAI_KEY",
                "缺少 XAI_API_KEY。导演台仍可人工上传，但 Grok Imagine 不能出图。",
            )
        self.base = os.environ.get("XAI_API_BASE", DEFAULT_BASE).rstrip("/")
        self.model = os.environ.get("XAI_IMAGE_MODEL", DEFAULT_MODEL)

    def generate(self, prompt: str, aspect: str = "16:9") -> bytes:
        payload = {
            "model": self.model,
            "prompt": self._aspect_prompt(prompt, aspect),
            "n": 1,
            "response_format": "b64_json",
            "aspect_ratio": aspect,
        }
        return self._post_json("/images/generations", payload)

    def edit(
        self,
        image: Path,
        prompt: str,
        refs: Optional[List[Path]] = None,
        aspect: str = "16:9",
    ) -> bytes:
        if not image.exists():
            raise ImagineError("MISSING_PARENT", f"父图不存在：{image}")
        files = [
            (
                "image",
                (
                    image.name,
                    image.read_bytes(),
                    mimetypes.guess_type(image.name)[0] or "image/jpeg",
                ),
            )
        ]
        for ref in (refs or [])[:4]:
            if ref.exists():
                files.append(
                    (
                        "image",
                        (
                            ref.name,
                            ref.read_bytes(),
                            mimetypes.guess_type(ref.name)[0] or "image/jpeg",
                        ),
                    )
                )
        data = {
            "model": self.model,
            "prompt": self._aspect_prompt(prompt, aspect),
            "n": "1",
            "response_format": "b64_json",
            "aspect_ratio": aspect,
        }
        response = requests.post(
            f"{self.base}/images/edits",
            headers=self._headers(json_mode=False),
            files=files,
            data=data,
            timeout=180,
        )
        if response.status_code >= 400:
            payload = {
                "model": self.model,
                "prompt": self._aspect_prompt(prompt, aspect),
                "n": 1,
                "response_format": "b64_json",
                "aspect_ratio": aspect,
                "image": {"url": self._data_url(image)},
            }
            try:
                return self._post_json("/images/edits", payload)
            except ImagineError:
                raise ImagineError(
                    "HTTP_ERROR",
                    f"Imagine 改图失败 {response.status_code}: {response.text[:400]}",
                ) from None
        return self._decode(response.json())

    def _headers(self, json_mode: bool = True) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if json_mode:
            headers["Content-Type"] = "application/json"
        return headers

    def _post_json(self, path: str, payload: dict) -> bytes:
        response = requests.post(
            f"{self.base}{path}",
            headers=self._headers(),
            json=payload,
            timeout=180,
        )
        if response.status_code >= 400:
            raise ImagineError(
                "HTTP_ERROR",
                f"Imagine 失败 {response.status_code}: {response.text[:400]}",
            )
        return self._decode(response.json())

    def _decode(self, body: dict) -> bytes:
        data = body.get("data") or []
        if not data:
            raise ImagineError("BAD_RESPONSE", f"Imagine 没有返回图片：{str(body)[:300]}")
        item = data[0]
        b64 = item.get("b64_json") or item.get("b64")
        if b64:
            return base64.b64decode(b64)
        url = item.get("url")
        if url:
            image = requests.get(url, timeout=180)
            image.raise_for_status()
            return image.content
        raise ImagineError("BAD_RESPONSE", f"Imagine 响应无法解码：{str(body)[:300]}")

    def _data_url(self, image: Path) -> str:
        mime = mimetypes.guess_type(image.name)[0] or "image/jpeg"
        return f"data:{mime};base64,{base64.b64encode(image.read_bytes()).decode('ascii')}"

    def _aspect_prompt(self, prompt: str, aspect: str) -> str:
        wide = aspect in {"16:9", "3:2", "4:3"}
        locked = (
            f"{'Widescreen landscape' if wide else 'Vertical'} still, aspect {aspect}, "
            "photoreal cinematic frame, no subtitles, no captions, no watermark, no title text. "
        )
        return locked + prompt
