"""Volcengine AK/SK calls: Ark OpenAPI (asset library) and TOS (private bucket staging).

Keys come from .env: VOLC_ACCESSKEY, VOLC_SECRETKEY, VOLC_TOS_BUCKET, VOLC_TOS_REGION.
Use a sub-user that holds only Ark + TOS rights. Never print the keys.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.parse
import urllib.request

ARK_HOST = "ark.cn-beijing.volcengineapi.com"
ARK_VERSION = "2024-01-01"


class VolcError(RuntimeError):
    def __init__(self, action: str, code: str, message: str) -> None:
        super().__init__(f"{action}: {code} {message}".strip())
        self.code = code


def _keys() -> tuple[str, str]:
    from director.paths import load_dotenv

    load_dotenv()
    ak = os.environ.get("VOLC_ACCESSKEY", "").strip()
    sk = os.environ.get("VOLC_SECRETKEY", "").strip()
    if not ak or not sk:
        raise SystemExit("set VOLC_ACCESSKEY / VOLC_SECRETKEY in .env (IAM sub-user with Ark + TOS rights)")
    return ak, sk


def _now() -> tuple[str, str]:
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")


def _signing_key(sk: str, short: str, region: str, service: str) -> bytes:
    key = sk.encode()
    for part in (short, region, service, "request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    return key


def _sign(algorithm: str, sk: str, xdate: str, short: str, region: str, service: str, canonical: str) -> tuple[str, str]:
    scope = f"{short}/{region}/{service}/request"
    to_sign = "\n".join([algorithm, xdate, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    sig = hmac.new(_signing_key(sk, short, region, service), to_sign.encode(), hashlib.sha256).hexdigest()
    return scope, sig


def ark_call(action: str, body: dict, *, region: str = "cn-beijing", timeout: int = 30) -> dict:
    """POST one Ark OpenAPI action; returns Result or raises VolcError."""
    ak, sk = _keys()
    payload = json.dumps(body, ensure_ascii=False).encode()
    xdate, short = _now()
    query = f"Action={action}&Version={ARK_VERSION}"
    digest = hashlib.sha256(payload).hexdigest()
    headers = {"content-type": "application/json", "host": ARK_HOST, "x-content-sha256": digest, "x-date": xdate}
    signed = ";".join(sorted(headers))
    canonical = "\n".join(["POST", "/", query, "".join(f"{k}:{headers[k]}\n" for k in sorted(headers)), signed, digest])
    scope, sig = _sign("HMAC-SHA256", sk, xdate, short, region, "ark", canonical)
    headers["authorization"] = f"HMAC-SHA256 Credential={ak}/{scope}, SignedHeaders={signed}, Signature={sig}"
    req = urllib.request.Request(f"https://{ARK_HOST}/?{query}", data=payload, headers=headers, method="POST")
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"{}")
    except urllib.error.HTTPError as err:
        try:
            data = json.loads(err.read() or b"{}")
        except json.JSONDecodeError:
            raise VolcError(action, f"HTTP_{err.code}", "") from err
    error = (data.get("ResponseMetadata") or {}).get("Error")
    if error:
        raise VolcError(action, str(error.get("Code") or ""), str(error.get("Message") or ""))
    return data.get("Result") or {}


def _tos() -> tuple[str, str, str, str]:
    ak, sk = _keys()
    bucket = os.environ.get("VOLC_TOS_BUCKET", "").strip()
    region = os.environ.get("VOLC_TOS_REGION", "cn-beijing").strip() or "cn-beijing"
    if not bucket:
        raise SystemExit("set VOLC_TOS_BUCKET in .env (private bucket for staging frames)")
    return ak, sk, region, f"{bucket}.tos-{region}.volces.com"


def _path(key: str) -> str:
    return "/" + urllib.parse.quote(key, safe="/-_.~")


def tos_request(method: str, key: str, data: bytes = b"", content_type: str = "", timeout: int = 120) -> int:
    ak, sk, region, host = _tos()
    xdate, short = _now()
    digest = hashlib.sha256(data).hexdigest()
    headers = {"host": host, "x-tos-content-sha256": digest, "x-tos-date": xdate}
    if content_type:
        headers["content-type"] = content_type
    signed = ";".join(sorted(headers))
    canonical = "\n".join([method, _path(key), "", "".join(f"{k}:{headers[k]}\n" for k in sorted(headers)), signed, digest])
    scope, sig = _sign("TOS4-HMAC-SHA256", sk, xdate, short, region, "tos", canonical)
    headers["authorization"] = f"TOS4-HMAC-SHA256 Credential={ak}/{scope}, SignedHeaders={signed}, Signature={sig}"
    req = urllib.request.Request(f"https://{host}{_path(key)}", data=data if method == "PUT" else None, headers=headers, method=method)
    try:
        return urllib.request.urlopen(req, timeout=timeout).status
    except urllib.error.HTTPError as err:
        if method == "DELETE" and err.code == 404:
            return 404
        raise VolcError(f"TOS {method}", f"HTTP_{err.code}", err.read()[:200].decode("utf-8", "replace")) from err


def tos_presign_get(key: str, expires: int = 900) -> str:
    """Short-lived signed GET for a private object. Only Ark should ever see it."""
    ak, sk, region, host = _tos()
    xdate, short = _now()
    scope = f"{short}/{region}/tos/request"
    params = {
        "X-Tos-Algorithm": "TOS4-HMAC-SHA256",
        "X-Tos-Credential": f"{ak}/{scope}",
        "X-Tos-Date": xdate,
        "X-Tos-Expires": str(expires),
        "X-Tos-SignedHeaders": "host",
    }
    query = "&".join(f"{urllib.parse.quote(k, safe='-_.~')}={urllib.parse.quote(v, safe='-_.~')}" for k, v in sorted(params.items()))
    canonical = "\n".join(["GET", _path(key), query, f"host:{host}\n", "host", "UNSIGNED-PAYLOAD"])
    _scope, sig = _sign("TOS4-HMAC-SHA256", sk, xdate, short, region, "tos", canonical)
    return f"https://{host}{_path(key)}?{query}&X-Tos-Signature={sig}"
