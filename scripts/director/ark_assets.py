"""Ark private virtual-portrait library: pass AI faces as asset:// instead of data URLs.

Seedance blocks AI faces sent as image bytes (PrivacyInformation). Frames that went through the
library's own review are accepted as `asset://asset-xxx`. Flow per frame:

    bytes -> private TOS object -> presigned GET -> CreateAsset -> poll Active -> delete TOS object

The ledger `.pipeline/ark_assets.json` maps file sha256 -> asset id, so the same bytes upload once.
The library holds 50 assets (Entry tier); `release` deletes them after the clips are kept.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from director.volc_openapi import VolcError, ark_call, tos_presign_get, tos_request

LEDGER = ".pipeline/ark_assets.json"
SCHEMA = "ark-assets-v1"
POLL_SEC = 3
TIMEOUT_SEC = 120


def ledger_path(prod: Path) -> Path:
    return prod / LEDGER


def read_ledger(prod: Path) -> dict:
    path = ledger_path(prod)
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {}
    data.setdefault("schema", SCHEMA)
    data.setdefault("groups", {})
    data.setdefault("assets", [])
    return data


def write_ledger(prod: Path, data: dict) -> None:
    path = ledger_path(prod)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def live_asset(data: dict, sha256: str) -> Optional[dict]:
    for item in data.get("assets") or []:
        if item.get("sha256") == sha256 and item.get("status") == "Active" and not item.get("released_at"):
            return item
    return None


def ensure_group(prod: Path, data: dict, name: str, description: str = "") -> str:
    group = (data.get("groups") or {}).get(name)
    if group:
        return group
    group = ark_call("CreateAssetGroup", {"Name": name[:64], "Description": description[:300], "GroupType": "AIGC"})["Id"]
    data["groups"][name] = group
    write_ledger(prod, data)
    return group


def _wait_active(asset_id: str, sleep: Callable[[float], None]) -> dict:
    waited = 0.0
    while True:
        result = ark_call("GetAsset", {"Id": asset_id})
        status = str(result.get("Status") or "")
        if status in {"Active", "Failed"}:
            return result
        if waited >= TIMEOUT_SEC:
            raise VolcError("GetAsset", "Timeout", f"{asset_id} still {status} after {TIMEOUT_SEC}s")
        sleep(POLL_SEC)
        waited += POLL_SEC


def ensure_asset(
    prod: Path,
    data_bytes: bytes,
    *,
    source: str,
    group_name: str,
    label: str,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Return `asset://...` for these exact bytes, uploading once."""
    sha = hashlib.sha256(data_bytes).hexdigest()
    data = read_ledger(prod)
    hit = live_asset(data, sha)
    if hit:
        return hit["url"]
    group = ensure_group(prod, data, group_name, f"{prod.name} {group_name}")
    suffix = Path(source).suffix.lower() or ".jpg"
    key = f"{prod.name}/{sha[:16]}{suffix}"
    tos_request("PUT", key, data_bytes, "image/png" if suffix == ".png" else "image/jpeg")
    try:
        asset_id = ark_call(
            "CreateAsset",
            {"GroupId": group, "URL": tos_presign_get(key), "AssetType": "Image", "Name": label[:64]},
        )["Id"]
        result = _wait_active(asset_id, sleep)
    finally:
        tos_request("DELETE", key)
    status = str(result.get("Status") or "")
    entry = {
        "source": source,
        "label": label,
        "sha256": sha,
        "group_id": group,
        "asset_id": asset_id,
        "url": f"asset://{asset_id}",
        "status": status,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    data = read_ledger(prod)
    data["assets"].append(entry)
    write_ledger(prod, data)
    if status != "Active":
        raise VolcError("CreateAsset", "ReviewFailed", f"{source} did not pass library review ({status})")
    return entry["url"]


def release(prod: Path, asset_ids: Optional[list[str]] = None) -> list[str]:
    """Delete assets from the library (all live ones by default) to free the 50-slot quota."""
    data = read_ledger(prod)
    gone: list[str] = []
    for item in data.get("assets") or []:
        aid = item.get("asset_id")
        if not aid or item.get("released_at") or (asset_ids is not None and aid not in asset_ids):
            continue
        try:
            ark_call("DeleteAsset", {"Id": aid})
        except VolcError as exc:
            if "NotFound" not in exc.code:
                raise
        item["released_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        gone.append(aid)
    write_ledger(prod, data)
    return gone
