#!/usr/bin/env python3
"""Append missing 009-siem-reap assets to .pipeline/assets.json without rewriting EP01 rows."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "productions" / "009-siem-reap"
ANTI = "皮肤有轻微深浅和自然纹理，不要磨皮，不要塑料感；高光哑光到半哑光，不要大片镜面油光；边缘不要过锐。"

NEW = [
    {
        "asset_id": "CHAR_PADONG_V1",
        "type": "character",
        "name": "帕东",
        "binds_to": "padong",
        "file": "02-assets/characters/padong/master.jpg",
        "what_it_locks": "身份（老水工）",
        "image_prompt": "standing passport, thin Khmer water worker, cloth clothes, axe at belt",
    },
    {
        "asset_id": "CHAR_PADONG_FACE_V1",
        "type": "character",
        "name": "帕东",
        "binds_to": "padong",
        "file": "02-assets/characters/padong/face.jpg",
        "what_it_locks": "脸锁（从 master 改）",
        "image_prompt": "face from padong master",
    },
    {
        "asset_id": "CHAR_SARI_V1",
        "type": "character",
        "name": "萨里",
        "binds_to": "sari",
        "file": "02-assets/characters/sari/master.jpg",
        "what_it_locks": "身份（王廷监军）",
        "image_prompt": "standing passport, Khmer court overseer, finer dark cloth",
    },
    {
        "asset_id": "CHAR_SARI_FACE_V1",
        "type": "character",
        "name": "萨里",
        "binds_to": "sari",
        "file": "02-assets/characters/sari/face.jpg",
        "what_it_locks": "脸锁（从 master 改）",
        "image_prompt": "face from sari master",
    },
    {
        "asset_id": "CHAR_SHAMON_V1",
        "type": "character",
        "name": "沙蒙",
        "binds_to": "shamon",
        "file": "02-assets/characters/shamon/master.jpg",
        "what_it_locks": "身份（暹罗统军）",
        "image_prompt": "standing passport, Siamese commander, metal armor",
    },
    {
        "asset_id": "CHAR_SHAMON_FACE_V1",
        "type": "character",
        "name": "沙蒙",
        "binds_to": "shamon",
        "file": "02-assets/characters/shamon/face.jpg",
        "what_it_locks": "脸锁（从 master 改）",
        "image_prompt": "face from shamon master",
    },
    {
        "asset_id": "LOC_OLD_SLUICE_V1",
        "type": "location",
        "name": "旧河口与旧闸",
        "binds_to": "old-sluice",
        "file": "02-assets/scenes/old-sluice/master.jpg",
        "what_it_locks": "空间（夜河口空镜）",
        "image_prompt": "empty night old river mouth with stone sluice left",
    },
    {
        "asset_id": "LOC_GRANARY_YARD_V1",
        "type": "location",
        "name": "粮栈外院",
        "binds_to": "granary-yard",
        "file": "02-assets/scenes/granary-yard/master.jpg",
        "what_it_locks": "空间（夜外院空镜）",
        "image_prompt": "empty night granary yard, left pillar right gate",
    },
    {
        "asset_id": "LOC_DRY_BED_V1",
        "type": "location",
        "name": "干河床交人处",
        "binds_to": "dry-bed",
        "file": "02-assets/scenes/dry-bed/master.jpg",
        "what_it_locks": "空间（正午干河床）",
        "image_prompt": "empty cracked dry riverbed, pale reeds",
    },
    {
        "asset_id": "LOC_ELEPHANT_CAMP_V1",
        "type": "location",
        "name": "暹罗象营洼地",
        "binds_to": "elephant-camp",
        "file": "02-assets/scenes/elephant-camp/master.jpg",
        "what_it_locks": "空间（象营空镜）",
        "image_prompt": "empty elephant camp posts and banners",
    },
    {
        "asset_id": "LOC_WATER_GATE_V1",
        "type": "location",
        "name": "水门石峡",
        "binds_to": "water-gate",
        "file": "02-assets/scenes/water-gate/master.jpg",
        "what_it_locks": "空间（水门空镜）",
        "image_prompt": "empty narrow stone gorge, fast water",
    },
    {
        "asset_id": "LOC_RIVER_BEND_V1",
        "type": "location",
        "name": "边寨外河湾",
        "binds_to": "river-bend",
        "file": "02-assets/scenes/river-bend/master.jpg",
        "what_it_locks": "空间（黄昏河湾）",
        "image_prompt": "empty dusk river bend",
    },
    {
        "asset_id": "PROP_AXE_V1",
        "type": "prop",
        "name": "斧",
        "binds_to": "axe",
        "file": "02-assets/props/axe/master.jpg",
        "what_it_locks": "道具",
        "image_prompt": "worn work axe still life",
    },
    {
        "asset_id": "PROP_SLUICE_BOARD_V1",
        "type": "prop",
        "name": "老闸板",
        "binds_to": "sluice-board",
        "file": "02-assets/props/sluice-board/master.jpg",
        "what_it_locks": "道具",
        "image_prompt": "old wooden sluice plank still life",
    },
    {
        "asset_id": "PROP_VINE_LASH_V1",
        "type": "prop",
        "name": "藤索",
        "binds_to": "vine-lash",
        "file": "02-assets/props/vine-lash/master.jpg",
        "what_it_locks": "道具",
        "image_prompt": "vine lash coil still life",
    },
    {
        "asset_id": "PROP_GRAIN_SACK_V1",
        "type": "prop",
        "name": "粮袋",
        "binds_to": "grain-sack",
        "file": "02-assets/props/grain-sack/master.jpg",
        "what_it_locks": "道具",
        "image_prompt": "burlap grain sacks still life",
    },
    {
        "asset_id": "PROP_HIDDEN_RAFT_V1",
        "type": "prop",
        "name": "暗铺木排",
        "binds_to": "hidden-raft",
        "file": "02-assets/props/hidden-raft/master.jpg",
        "what_it_locks": "道具",
        "image_prompt": "camouflaged raft with gourd floats",
    },
    {
        "asset_id": "CHAR_GUIDE_V1",
        "type": "character",
        "name": "导游",
        "binds_to": "guide",
        "file": "02-assets/characters/guide/master.jpg",
        "what_it_locks": "身份（现代导游）",
        "image_prompt": "standing passport, modern modest civilian clothes",
    },
]


def main() -> int:
    path = PROD / ".pipeline" / "assets.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    have = {item.get("asset_id") for item in data.get("assets") or []}
    added = []
    for raw in NEW:
        if raw["asset_id"] in have:
            continue
        file_path = PROD / raw["file"]
        if not file_path.exists():
            print(f"skip missing file {raw['file']}", file=sys.stderr)
            continue
        item = dict(raw)
        item["version"] = "v1"
        item["lock_card"] = [
            {"key": "slug", "value": item["binds_to"], "source": "script"},
            {"key": "people", "value": "静物" if item["type"] == "prop" else "", "source": "岗位默认" if item["type"] != "prop" else "岗位"},
        ]
        if item["type"] in {"character", "costume_state"}:
            item["quality_layer"] = ANTI
        data["assets"].append(item)
        added.append(item["asset_id"])
    data["updated_at"] = int(time.time())
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"added": added, "total": len(data["assets"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
