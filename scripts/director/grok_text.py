"""Grok text for station agents.

Prefer the local Grok/OpenCodex subscription proxy. XAI_API_KEY is optional.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

import requests


OFFICIAL_BASE = "https://api.x.ai/v1"
OFFICIAL_MODEL = "grok-4.6"
SUBSCRIPTION_BASE = "http://127.0.0.1:10100/v1"
SUBSCRIPTION_MODEL = "xai/grok-4.6"


class TextError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _disabled_subscription() -> bool:
    return os.environ.get("DIRECTOR_DISABLE_GROK_SUBSCRIPTION", "").strip().lower() in {"1", "true", "yes"}


def official_key() -> str:
    return os.environ.get("XAI_API_KEY", "").strip()


def subscription_base() -> str:
    return os.environ.get("GROK_SUBSCRIPTION_BASE", SUBSCRIPTION_BASE).rstrip("/")


def subscription_up() -> bool:
    if _disabled_subscription():
        return False
    root = subscription_base()
    if root.endswith("/v1"):
        root = root[:-3]
    try:
        response = requests.get(root.rstrip("/") + "/healthz", timeout=0.5)
        if response.status_code < 500:
            return True
    except Exception:
        pass
    try:
        response = requests.get(subscription_base() + "/models", timeout=0.5)
        return response.status_code < 500
    except Exception:
        return False


def text_backend() -> str:
    if subscription_up():
        return "grok-subscription"
    if official_key():
        return "xai-key"
    return ""


def text_configured() -> bool:
    return bool(text_backend())


def chat_json(
    system: str,
    user: str,
    *,
    model: Optional[str] = None,
    timeout: int = 90,
    temperature: float = 0.2,
    effort: Optional[str] = None,
    max_tokens: Optional[int] = None,
) -> Any:
    backend = text_backend()
    if backend == "xai-key":
        base = os.environ.get("XAI_API_BASE", OFFICIAL_BASE).rstrip("/")
        chosen = model or os.environ.get("XAI_TEXT_MODEL", OFFICIAL_MODEL)
        headers = {
            "Authorization": "Bearer " + official_key(),
            "Content-Type": "application/json",
        }
    elif backend == "grok-subscription":
        base = subscription_base()
        chosen = model or os.environ.get("XAI_TEXT_MODEL", SUBSCRIPTION_MODEL)
        if chosen == OFFICIAL_MODEL:
            chosen = SUBSCRIPTION_MODEL
        headers = {"Content-Type": "application/json"}
    else:
        raise TextError(
            "NEED_GROK_LOGIN",
            "本机没有可用的 Grok 订阅代理，也没有 XAI_API_KEY。先登录 Grok/OpenCodex，或启动 opencodex。",
        )
    payload = {
        "model": chosen,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if max_tokens:
        payload["max_tokens"] = int(max_tokens)
    if backend == "grok-subscription":
        payload["reasoning"] = {"effort": effort or os.environ.get("GROK_REASONING_EFFORT", "low")}
    response = requests.post(
        f"{base}/chat/completions",
        headers=headers,
        json=payload,
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise TextError("GROK_HTTP", f"Grok 文本接口 {response.status_code}: {response.text[:400]}")
    data = response.json()
    content = (
        ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    ).strip()
    if not content:
        raise TextError("GROK_EMPTY", "Grok 没有返回文本")
    return parse_json_content(content)


def parse_json_content(content: str) -> Any:
    raw = content.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fenced:
        raw = fenced.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        # Closed the shots array too early, then kept emitting shot objects.
        premature = re.sub(r"\]\s*,\s*(\{\"shot_id\")", r",\1", raw, count=1)
        if premature != raw:
            try:
                return json.loads(premature)
            except json.JSONDecodeError:
                pass
        if start >= 0:
            # One complete object followed by extra text (a repeated object, a note): keep the first object.
            try:
                obj, _end = json.JSONDecoder().raw_decode(raw, start)
                return obj
            except json.JSONDecodeError:
                pass
        if start >= 0 and end > start:
            snippet = raw[start : end + 1]
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                repaired = re.sub(r",\s*([}\]])", r"\1", snippet)
                repaired = repaired.replace("\n", " ").replace("\t", " ")
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError as exc:
                    raise TextError("GROK_JSON", f"Grok 没有返回 JSON: {exc}") from exc
        raise TextError("GROK_JSON", "Grok 没有返回 JSON")
