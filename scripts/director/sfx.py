"""Episode SFX bed from locked shot-table key_sfx + real 05-shots durations.

Recipe-first: the locked table is the contract. Freesound only fills missing kit
files. Does not read or write 03-storyboard/shots.json. Does not mix VO or BGM.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Optional

import requests

from .paths import media_url
from .pipeline import read_artifact, write_artifact

# query: one string, or fallbacks tried in order. Optional TAG_FREESOUND_IDS pins a known file.
TAG_QUERIES: dict[str, tuple[str | tuple[str, ...], float, float]] = {
    "river": ("flowing river water", 6, 20),
    "rain": ("heavy rain downpour", 6, 18),
    "splash": ("big water splash", 1, 4),
    "shore": ("river water lapping shore", 4, 12),
    "footsteps": ("footsteps running dirt", 1, 4),
    "tackle": ("body fall on dirt", 0.6, 3),
    "drum": ("distant war drum", 2, 8),
    "elephant": ("elephant trumpet", 1, 6),
    "rope": ("rope pull tighten", 0.6, 3),
    "arrow": ("arrow whoosh", 0.4, 2),
    "arrow_hit": ("arrow hit", 0.4, 2),
    "horse": ("horse neigh", 1, 5),
    "horse_water": ("horse splash water", 1, 5),
    "mud": ("mud splash", 0.6, 3),
    "underwater": ("underwater current", 3, 12),
    "night": ("night crickets ambience", 6, 20),
    "fire": ("campfire crackle", 5, 16),
    "reeds": ("reeds wind night", 4, 12),
    "drip": ("water dripping", 2, 8),
    "torch_out": ("fire extinguish sizzle", 0.6, 3),
    "thunder": ("distant thunder rumble", 2, 8),
    "cart_bump": (("trolley", "shopping cart wheel", "metal clank"), 0.3, 4),
    "keys_drop": (("dropping keys", "keychain drop", "keys jingle"), 0.2, 4),
    "broom_sweep": (("broom sweeping floor", "sweeping concrete"), 1, 8),
    "cabinet_squeak": (("creaky metal door", "metal cabinet door squeak"), 0.5, 4),
    "cloth_wipe": (("window wipe", "wiping cloth", "wiping glass"), 0.4, 3),
    "cabinet_bump": (("locker slam", "hitting metal", "metal bang"), 0.3, 3),
    "broom_drop": (("wooden rod drop", "stick drop floor"), 0.3, 2),
    "door_call": (("muffled speech", "door knock"), 0.5, 4),
    "footsteps_indoor": (("footsteps concrete indoor", "footsteps walking indoor"), 1, 6),
    "cloth_throw": (("dropping fabric onto floor", "dropping clothes"), 0.3, 4),
    "pen_click": (("pen cap", "pen click"), 0.2, 2),
    "pocket": (("cloth pocket rustle", "hand in pocket"), 0.3, 2),
    "badge": (("plastic card tap", "id badge"), 0.2, 2),
    "factory": (("factory sewing machines", "industrial factory ambience"), 6, 20),
    "factory_yard": (("street traffic distant", "city traffic ambience"), 6, 20),
    "room_tone": (("quiet room tone", "fluorescent hum room"), 6, 20),
}

# Prefer these Freesound IDs over first-search-wins (factory kit; war tags stay search-based).
TAG_FREESOUND_IDS: dict[str, int] = {
    "cart_bump": 233059,
    "keys_drop": 740407,
    "broom_sweep": 496724,
    "cabinet_squeak": 426422,
    "cloth_wipe": 154383,
    "cabinet_bump": 449521,
    "broom_drop": 774269,
    "door_call": 792363,
    "footsteps_indoor": 740419,
    "cloth_throw": 768130,
    "pen_click": 829807,
    "factory": 423448,
    "factory_yard": 189862,
    "room_tone": 454166,
}

# First matching needle wins. Order matters (人马 before 马, 脚步不停 before 脚步).
LABEL_RULES: list[tuple[tuple[str, ...], list[str], str]] = [
    (("雷", "thunder"), ["thunder"], "spot"),
    (("暴雨", "雨砸", "downpour"), ["rain"], "bed"),
    (("落水", "坠河", "没入", "吞人", "滚进"), ["splash"], "spot"),
    (("呛水", "拍岸"), ["shore", "splash"], "spot"),
    (("象鸣", "象蹄", "象"), ["elephant"], "spot"),
    (("踏水",), ["horse_water"], "spot"),
    (("战鼓", "鼓"), ["drum"], "spot"),
    (("麻绳", "草绳", "绳"), ["rope"], "spot"),
    (("箭", "arrow"), ["arrow", "arrow_hit"], "spot"),
    (("人马", "陷泥"), ["horse", "horse_water", "mud"], "spot"),
    (("马",), ["horse"], "spot"),
    (("沉木", "水下", "水里"), ["underwater"], "bed"),
    (("火把熄", "熄灭", "噼啪"), ["torch_out"], "spot"),
    (("滴水", "漏水", "滴答"), ["drip"], "bed"),
    (("车轮", "门槛"), ["cart_bump"], "spot"),
    (("钥匙扔", "钥匙落", "钥匙"), ["keys_drop"], "spot"),
    (("扫帚刮", "刮地", "扫地"), ["broom_sweep"], "spot"),
    (("柜门吱", "吱呀"), ["cabinet_squeak"], "spot"),
    (("抹灰", "抹掉"), ["cloth_wipe"], "spot"),
    (("退撞", "撞柜"), ["cabinet_bump"], "spot"),
    (("扫把掉", "扫帚掉", "扫把落"), ["broom_drop"], "spot"),
    (("门外喊", "门外叫"), ["door_call"], "spot"),
    (("脚步不停",), ["footsteps_indoor"], "bed"),
    (("布甩", "甩在地上"), ["cloth_throw"], "spot"),
    (("笔帽",), ["pen_click"], "spot"),
    (("口袋", "塞进"), ["pocket"], "spot"),
    (("工牌", "刷卡"), ["badge"], "spot"),
    (("脚步", "跑"), ["footsteps"], "spot"),
    (("按倒", "扑倒", "摔倒"), ["tackle"], "spot"),
]

WATER_LOCS = ("channel", "river", "shoal", "water", "河", "滩", "漕")
NIGHT_LOCS = ("camp", "village", "寨", "night")
FACTORY_YARD_LOCS = ("factory-gate", "factory-yard", "factory-road", "厂门")
STOREROOM_LOCS = ("storeroom", "杂物")
FACTORY_FLOOR_LOCS = ("factory", "line-7", "workshop", "车间", "厂办", "sewing")
STORM_WORDS = ("storm", "rain", "暴雨")
NIGHT_WORDS = ("night", "夜")
OVERRIDE_SCHEMA = "sfx-overrides-v1"


def episode_slug(episode: int) -> str:
    return f"ep{int(episode):02d}"


def sfx_dir(prod: Path) -> Path:
    return prod / "07-dubbing" / "sfx"


def shot_list_path(prod: Path, episode: int) -> Path:
    if int(episode) != 1:
        alt = prod / ".pipeline" / f"shot_list.ep{int(episode):02d}.json"
        if alt.exists():
            return alt
    return prod / ".pipeline" / "shot_list.json"


def load_shot_table(prod: Path, episode: int = 1) -> dict:
    path = shot_list_path(prod, episode)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    return read_artifact(prod, "shot_list.json")


def labels_to_tags(labels: list[str] | str | None) -> list[dict]:
    """Map Chinese (or English) key_sfx labels to kit tags. Unknown labels are skipped."""
    if isinstance(labels, str):
        raw = [part.strip() for part in labels.replace("，", "、").replace(",", "、").split("、") if part.strip()]
    else:
        raw = [str(item).strip() for item in (labels or []) if str(item).strip()]
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for label in raw:
        matched = False
        for needles, tags, kind in LABEL_RULES:
            if any(needle in label for needle in needles):
                matched = True
                for tag in tags:
                    key = (tag, kind)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({"label": label, "tag": tag, "kind": kind})
                break
        if not matched:
            out.append({"label": label, "tag": "", "kind": "", "unmapped": True})
    return out


def day_night_of(shot: dict) -> str:
    light = shot.get("light")
    if isinstance(light, dict) and light.get("day_night"):
        return str(light.get("day_night") or "")
    return str(shot.get("day_night") or "")


def has_dialogue(shot: dict) -> bool:
    refs = shot.get("dialogue_ref") or []
    if refs:
        return True
    delivery = str(shot.get("dialogue_delivery") or "").strip().lower()
    return bool(delivery) and delivery not in {"none", "mute", "无", "n/a"}


def _blob(*parts: Any) -> str:
    return " ".join(str(p or "") for p in parts).lower()


def probe_duration(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        text=True,
    ).strip()
    return float(out)


def shot_timeline(
    prod: Path,
    shot_ids: list[str],
    *,
    fallback: Optional[dict[str, float]] = None,
) -> tuple[list[dict], list[str]]:
    shots_dir = prod / "05-shots"
    items: list[dict] = []
    missing: list[str] = []
    t = 0.0
    for sid in shot_ids:
        path = shots_dir / f"{sid}.mp4"
        if path.exists():
            dur = probe_duration(path)
            file_path = str(path)
        elif fallback and sid in fallback:
            dur = float(fallback[sid])
            file_path = ""
        else:
            missing.append(sid)
            continue
        items.append({
            "shot_id": sid,
            "start": t,
            "duration": dur,
            "end": t + dur,
            "file": file_path,
        })
        t += dur
    return items, missing


def load_overrides(prod: Path) -> Optional[dict]:
    path = sfx_dir(prod) / "overrides.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _kit_path(prod: Path, tag: str) -> Optional[Path]:
    path = sfx_dir(prod) / "kit" / f"{tag}.mp3"
    if path.exists() and path.stat().st_size > 2000:
        return path
    if tag == "thunder":
        legacy = sfx_dir(prod) / "thunder-cc0.mp3"
        if legacy.exists() and legacy.stat().st_size > 2000:
            return legacy
    return None


def attach_files(prod: Path, events: list[dict]) -> tuple[list[dict], list[str]]:
    ready: list[dict] = []
    missing: list[str] = []
    for ev in events:
        tag = ev.get("tag") or ""
        path = _kit_path(prod, tag)
        if not path:
            if tag and tag not in missing:
                missing.append(tag)
            continue
        item = dict(ev)
        item["file"] = str(path)
        ready.append(item)
    return ready, missing


def resolve_overrides(overrides: dict, timeline: list[dict]) -> list[dict]:
    by = {item["shot_id"]: item for item in timeline}
    events: list[dict] = []
    for bed in overrides.get("beds") or []:
        start_shot = by.get(bed.get("from_shot"))
        end_shot = by.get(bed.get("to_shot")) or start_shot
        if not start_shot or not end_shot:
            continue
        events.append({
            "kind": "loop",
            "tag": bed.get("tag"),
            "start": start_shot["start"],
            "end": end_shot["end"],
            "vol": float(bed.get("vol") or 0.2),
        })
    for spot in overrides.get("spots") or []:
        shot = by.get(spot.get("shot_id"))
        if not shot:
            continue
        if spot.get("from_end") is not None:
            at = shot["end"] + float(spot.get("from_end"))
        else:
            at = shot["start"] + float(spot.get("at_sec") or 0)
        events.append({
            "kind": "spot",
            "tag": spot.get("tag"),
            "at": max(0.0, at),
            "vol": float(spot.get("vol") or 0.45),
            "shot_id": shot["shot_id"],
            "why": spot.get("why") or "",
        })
    return events


def plan_events(table_shots: list[dict], timeline: list[dict]) -> list[dict]:
    """Build loop + spot events from key_sfx, location, weather, and internal_cuts."""
    by_time = {item["shot_id"]: item for item in timeline}
    rows = [shot for shot in table_shots if shot.get("shot_id") in by_time]
    events: list[dict] = []

    def bed(tag: str, start: float, end: float, vol: float) -> None:
        if end - start < 0.2:
            return
        events.append({"kind": "loop", "tag": tag, "start": start, "end": end, "vol": vol})

    def spot(tag: str, at: float, vol: float, shot_id: str, why: str) -> None:
        events.append({
            "kind": "spot",
            "tag": tag,
            "at": max(0.0, at),
            "vol": vol,
            "shot_id": shot_id,
            "why": why,
        })

    scene_groups: list[list[dict]] = []
    for shot in rows:
        if not scene_groups or (scene_groups[-1][-1].get("scene_id") != shot.get("scene_id")):
            scene_groups.append([shot])
        else:
            scene_groups[-1].append(shot)

    for group in scene_groups:
        first = by_time[group[0]["shot_id"]]
        last = by_time[group[-1]["shot_id"]]
        loc = _blob(*(s.get("location_id") for s in group))
        weather = _blob(*(day_night_of(s) for s in group), *( " ".join(s.get("key_sfx") or []) for s in group))
        quiet = 0.16 if any(has_dialogue(s) for s in group) else 0.22
        if any(word in loc for word in WATER_LOCS):
            bed("river", first["start"], last["end"], quiet)
        if any(word in loc for word in FACTORY_YARD_LOCS):
            bed("factory_yard", first["start"], last["end"], quiet)
        elif any(word in loc for word in STOREROOM_LOCS):
            bed("room_tone", first["start"], last["end"], 0.12 if quiet < 0.2 else 0.16)
        elif any(word in loc for word in FACTORY_FLOOR_LOCS):
            bed("factory", first["start"], last["end"], quiet)
        if any(word in weather for word in STORM_WORDS):
            storm_from = next(
                (by_time[s["shot_id"]]["start"] for s in group if any(w in _blob(day_night_of(s), " ".join(s.get("key_sfx") or [])) for w in STORM_WORDS)),
                first["start"],
            )
            bed("rain", storm_from, last["end"], 0.34)
        if any(word in weather or word in loc for word in NIGHT_WORDS) or any(word in loc for word in NIGHT_LOCS):
            if any(word in weather or word in loc for word in NIGHT_WORDS):
                bed("night", first["start"], last["end"], 0.16)
                if any(word in loc for word in NIGHT_LOCS):
                    bed("fire", first["start"], last["end"], 0.16)
                    bed("reeds", first["start"], min(first["start"] + 14, last["end"]), 0.12)

    prev: Optional[dict] = None
    for shot in rows:
        timed = by_time[shot["shot_id"]]
        mapped = [item for item in labels_to_tags(shot.get("key_sfx")) if item.get("tag")]
        for item in mapped:
            if item["kind"] == "bed":
                bed(item["tag"], timed["start"], timed["end"], 0.24 if item["tag"] == "underwater" else 0.18)
        spots = [item for item in mapped if item["kind"] == "spot"]
        cuts = [float(c.get("at_sec")) for c in (shot.get("internal_cuts") or []) if c.get("at_sec") is not None]
        splash_why = next((item.get("label") for item in spots if item["tag"] == "splash"), "落水")
        if any(item["tag"] == "splash" for item in spots) and cuts:
            for cut in cuts:
                spot("splash", timed["start"] + cut, 0.68, shot["shot_id"], splash_why)
            spots = [item for item in spots if item["tag"] != "splash"]
        placed = 0
        used_cuts = 0
        for item in spots:
            tag = item["tag"]
            why = item.get("label") or tag
            if tag == "thunder":
                if prev:
                    spot("thunder", by_time[prev["shot_id"]]["end"] - 1.2, 0.45, prev["shot_id"], why + "（远处）")
                spot("thunder", timed["start"], 0.70, shot["shot_id"], why)
                placed += 1
                continue
            if tag == "torch_out" and timed["duration"] >= 8:
                for offset, vol in ((2.2, 0.34), (5.0, 0.32), (8.0, 0.30)):
                    if offset < timed["duration"] - 0.2:
                        spot("torch_out", timed["start"] + offset, vol, shot["shot_id"], why)
                placed += 1
                continue
            offset = 0.2 + placed * 0.9
            if used_cuts < len(cuts) and tag not in {"arrow_hit"}:
                offset = cuts[used_cuts]
                used_cuts += 1
            spot(tag, timed["start"] + offset, 0.52 if tag != "arrow_hit" else 0.55, shot["shot_id"], why)
            placed += 1
        prev = shot
    return events


def fetch_kit(prod: Path, tags: list[str], api_key: str) -> dict:
    kit = sfx_dir(prod) / "kit"
    kit.mkdir(parents=True, exist_ok=True)
    manifest_path = kit / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    thunder = sfx_dir(prod) / "thunder-cc0.mp3"
    dest_thunder = kit / "thunder.mp3"
    if thunder.exists() and not dest_thunder.exists():
        dest_thunder.write_bytes(thunder.read_bytes())
        meta_path = sfx_dir(prod) / "thunder-cc0.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        manifest["thunder"] = {
            "tag": "thunder",
            "file": "kit/thunder.mp3",
            "freesound_id": meta.get("freesound_id"),
            "name": meta.get("name"),
            "username": meta.get("username"),
            "license": meta.get("license"),
            "page": meta.get("page"),
            "duration_sec": meta.get("duration_sec"),
        }
    session = requests.Session()
    for tag in tags:
        if tag not in TAG_QUERIES and tag not in TAG_FREESOUND_IDS:
            continue
        dest = kit / f"{tag}.mp3"
        if dest.exists() and dest.stat().st_size > 2000 and tag in manifest:
            continue
        hit, query = _resolve_freesound(session, api_key, tag)
        if not hit:
            continue
        audio = session.get(hit["_preview"], timeout=60)
        audio.raise_for_status()
        dest.write_bytes(audio.content)
        manifest[tag] = {
            "tag": tag,
            "query": query,
            "file": f"kit/{tag}.mp3",
            "freesound_id": hit["id"],
            "name": hit["name"],
            "username": hit.get("username"),
            "license": hit.get("license"),
            "page": hit.get("url"),
            "duration_sec": hit.get("duration"),
        }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _tag_query_list(tag: str) -> tuple[tuple[str, ...], float, float]:
    spec = TAG_QUERIES.get(tag)
    if not spec:
        return (), 0.0, 0.0
    query, lo, hi = spec
    queries = query if isinstance(query, tuple) else (query,)
    return queries, float(lo), float(hi)


def _attach_preview(item: dict) -> Optional[dict]:
    preview = (item.get("previews") or {}).get("preview-hq-mp3")
    if not preview:
        return None
    item["_preview"] = preview
    return item


def _get_freesound(session: requests.Session, key: str, sound_id: int) -> Optional[dict]:
    url = f"https://freesound.org/apiv2/sounds/{int(sound_id)}/"
    params = {
        "fields": "id,name,duration,license,username,url,tags,previews",
        "token": key,
    }
    resp = session.get(url, params=params, timeout=30)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return _attach_preview(resp.json())


def _resolve_freesound(session: requests.Session, key: str, tag: str) -> tuple[Optional[dict], str]:
    pinned = TAG_FREESOUND_IDS.get(tag)
    if pinned:
        hit = _get_freesound(session, key, pinned)
        if hit:
            return hit, f"freesound:{pinned}"
    queries, lo, hi = _tag_query_list(tag)
    for query in queries:
        hit = _search_freesound(session, key, query, lo, hi)
        if hit:
            return hit, query
    return None, ""


def _search_freesound(session: requests.Session, key: str, query: str, lo: float, hi: float) -> Optional[dict]:
    url = "https://freesound.org/apiv2/search/text/"
    for license_filter in ('license:"Creative Commons 0"', 'license:"Attribution"'):
        params = {
            "query": query,
            "filter": f"{license_filter} duration:[{lo} TO {hi}]",
            "fields": "id,name,duration,license,username,url,tags,previews",
            "page_size": 5,
            "sort": "score",
            "token": key,
        }
        resp = session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        for item in resp.json().get("results") or []:
            attached = _attach_preview(item)
            if attached:
                return attached
    return None


def mix(events: list[dict], duration: float, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={duration:.3f}"]
    filters = ["[0:a]volume=0[silence]"]
    names = ["[silence]"]
    for i, ev in enumerate(events):
        if ev["kind"] == "loop":
            cmd += ["-stream_loop", "-1", "-i", ev["file"]]
        else:
            cmd += ["-i", ev["file"]]
        idx = i + 1
        if ev["kind"] == "loop":
            start = ev["start"]
            dur = max(0.2, ev["end"] - ev["start"])
            delay = int(start * 1000)
            fade = min(0.8, dur / 4)
            filters.append(
                f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                f"atrim=0:{dur:.3f},asetpts=PTS-STARTPTS,"
                f"afade=t=in:d={fade:.2f},afade=t=out:st={max(0.1, dur - fade):.3f}:d={fade:.2f},"
                f"adelay={delay}|{delay},volume={ev['vol']}[e{i}]"
            )
        else:
            delay = int(ev["at"] * 1000)
            filters.append(
                f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                f"asetpts=PTS-STARTPTS,adelay={delay}|{delay},volume={ev['vol']}[e{i}]"
            )
        names.append(f"[e{i}]")
    filters.append(
        "".join(names)
        + f"amix=inputs={len(names)}:duration=longest:dropout_transition=0:normalize=0,"
        + f"alimiter=limit=0.95,atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[a]"
    )
    cmd += ["-filter_complex", ";".join(filters), "-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(dest)]
    subprocess.check_call(cmd)


def mux_preview(prod: Path, shots: list[dict], audio: Path, dest: Path) -> None:
    work = sfx_dir(prod)
    work.mkdir(parents=True, exist_ok=True)
    listing = work / "_concat.txt"
    lines = []
    for item in shots:
        path = Path(item["file"]).resolve().as_posix().replace("'", r"'\''")
        lines.append(f"file '{path}'")
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    silent = work / "_picture.mp4"
    subprocess.check_call(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(listing),
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent),
        ]
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(silent), "-i", str(audio),
            "-c:v", "copy", "-c:a", "aac", "-shortest", str(dest),
        ]
    )
    silent.unlink(missing_ok=True)
    listing.unlink(missing_ok=True)


def _public_events(prod: Path, events: list[dict]) -> list[dict]:
    root = sfx_dir(prod)
    out = []
    for ev in events:
        item = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in ev.items() if k != "file"}
        raw = ev.get("file")
        if raw:
            path = Path(raw)
            try:
                item["file"] = str(path.resolve().relative_to(root.resolve()))
            except ValueError:
                item["file"] = str(path)
        out.append(item)
    return out


def build_plan(prod: Path, episode: int = 1, *, allow_table_duration: bool = False) -> dict:
    table = load_shot_table(prod, episode)
    table_shots = [s for s in (table.get("shots") or []) if s.get("shot_id")]
    ids = [s["shot_id"] for s in table_shots]
    fallback = {s["shot_id"]: float(s.get("duration_sec") or 0) for s in table_shots} if allow_table_duration else None
    timeline, missing_clips = shot_timeline(prod, ids, fallback=fallback)
    overrides = load_overrides(prod)
    source = "overrides" if overrides else "shot_table"
    planned = resolve_overrides(overrides, timeline) if overrides else plan_events(table_shots, timeline)
    duration = timeline[-1]["end"] if timeline else 0.0
    needed = sorted({ev.get("tag") for ev in planned if ev.get("tag")})
    missing_kit = [tag for tag in needed if not _kit_path(prod, tag)]
    unmapped = []
    if not overrides:
        for shot in table_shots:
            for item in labels_to_tags(shot.get("key_sfx")):
                if item.get("unmapped"):
                    unmapped.append(f"{shot.get('shot_id')} {item.get('label')}")
    return {
        "schema": "sfx-plan-v1",
        "prod": prod.name,
        "episode": int(episode),
        "episode_slug": episode_slug(episode),
        "source": source,
        "writes_shots_json": False,
        "duration_sec": duration,
        "shot_count": len(timeline),
        "missing_clips": missing_clips,
        "missing_kit": missing_kit,
        "unmapped_labels": unmapped,
        "event_count": len(planned),
        "events": planned,
        "shots": [{"shot_id": s["shot_id"], "start": s["start"], "end": s["end"]} for s in timeline],
        "timeline": timeline,
        "needed_tags": needed,
        "has_overrides": bool(overrides),
        "audio": f"07-dubbing/sfx/{episode_slug(episode)}-sfx.m4a",
        "cues": f"07-dubbing/sfx/{episode_slug(episode)}-sfx.cues.json",
        "preview": f"06-export/{episode_slug(episode)}-sfx-preview.mp4",
    }


def write_audio_fields(prod: Path, plan: dict) -> dict:
    audio = dict(read_artifact(prod, "audio.json") or {})
    audio["episode_no"] = plan["episode"]
    audio["sfx_file"] = plan["audio"]
    audio["ambience_file"] = plan["audio"]
    audio["sfx_cues"] = plan["cues"]
    if (prod / plan["preview"]).exists():
        audio["sfx_preview"] = plan["preview"]
    audio.setdefault("dialogue_takes", audio.get("dialogue_takes") or [])
    audio.setdefault("vo_takes", audio.get("vo_takes") or [])
    audio.setdefault("status", "draft")
    return write_artifact(prod, "audio.json", audio)


def snapshot_sfx(prod: Path, episode: int = 1) -> dict:
    slug = episode_slug(episode)
    rel_audio = f"07-dubbing/sfx/{slug}-sfx.m4a"
    rel_cues = f"07-dubbing/sfx/{slug}-sfx.cues.json"
    rel_preview = f"06-export/{slug}-sfx-preview.mp4"
    table = load_shot_table(prod, episode)
    shots = [s for s in (table.get("shots") or []) if s.get("shot_id")]
    missing = [s["shot_id"] for s in shots if not (prod / "05-shots" / f"{s['shot_id']}.mp4").exists()]
    cues = {}
    cues_path = prod / rel_cues
    if cues_path.exists():
        try:
            cues = json.loads(cues_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cues = {}
    key_sfx = [{"shot_id": s.get("shot_id"), "key_sfx": list(s.get("key_sfx") or [])} for s in shots if s.get("key_sfx")]
    return {
        "episode": int(episode),
        "file": rel_audio,
        "exists": (prod / rel_audio).exists(),
        "url": media_url(prod, rel_audio),
        "preview": rel_preview,
        "preview_exists": (prod / rel_preview).exists(),
        "preview_url": media_url(prod, rel_preview),
        "duration_sec": cues.get("duration_sec"),
        "event_count": len(cues.get("events") or []),
        "has_overrides": (sfx_dir(prod) / "overrides.json").exists(),
        "missing_clips": missing,
        "key_sfx": key_sfx,
        "clip_count": len(shots) - len(missing),
        "shot_count": len(shots),
        "note": "按锁定分镜表 key_sfx 混一条整集音效床。Seedance 自带声不当成品。",
    }


def run_mix(
    prod: Path,
    *,
    episode: int = 1,
    dry_run: bool = False,
    force: bool = False,
    preview: bool = True,
) -> dict:
    if not prod.is_dir():
        raise ValueError(f"没有这个项目：{prod}")
    plan = build_plan(prod, episode, allow_table_duration=dry_run)
    dest = prod / plan["audio"]
    if plan["missing_clips"] and not dry_run:
        raise ValueError("还缺单镜视频：" + ", ".join(plan["missing_clips"]))
    if not plan["timeline"]:
        raise ValueError("分镜表没有镜头，无法排音效时间轴")
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "prod": prod.name,
            "episode": episode,
            "duration_sec": plan["duration_sec"],
            "event_count": plan["event_count"],
            "source": plan["source"],
            "missing_clips": plan["missing_clips"],
            "missing_kit": plan["missing_kit"],
            "unmapped_labels": plan["unmapped_labels"],
            "audio": plan["audio"],
            "writes_shots_json": False,
            "sfx": snapshot_sfx(prod, episode),
        }
    if dest.exists() and dest.stat().st_size > 2000 and not force:
        write_audio_fields(prod, plan)
        snap = snapshot_sfx(prod, episode)
        return {
            "ok": True,
            "dry_run": False,
            "skipped": True,
            "prod": prod.name,
            "episode": episode,
            "duration_sec": plan["duration_sec"],
            "event_count": snap.get("event_count") or plan["event_count"],
            "audio": plan["audio"],
            "preview": plan["preview"] if (prod / plan["preview"]).exists() else None,
            "note": "已有音效床，未重混。要重做就加 --force。",
            "sfx": snap,
        }
    ready, missing_kit = attach_files(prod, plan["events"])
    if missing_kit:
        key = os.environ.get("FREESOUND_API_KEY", "").strip()
        if not key:
            raise ValueError("缺音效素材 " + ", ".join(missing_kit) + "。把文件放进 07-dubbing/sfx/kit/，或设 FREESOUND_API_KEY。")
        fetch_kit(prod, missing_kit, key)
        ready, missing_kit = attach_files(prod, plan["events"])
    if missing_kit:
        raise ValueError("Freesound 仍缺素材：" + ", ".join(missing_kit))
    mix(ready, plan["duration_sec"], dest)
    cues = {
        "schema": "sfx-cues-v1",
        "episode": episode_slug(episode),
        "duration_sec": plan["duration_sec"],
        "audio": plan["audio"],
        "preview": plan["preview"],
        "source": plan["source"],
        "shots": [{"shot_id": s["shot_id"], "start": round(s["start"], 3), "end": round(s["end"], 3)} for s in plan["timeline"]],
        "events": _public_events(prod, ready),
    }
    (prod / plan["cues"]).write_text(json.dumps(cues, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    preview_rel = None
    if preview:
        mux_preview(prod, plan["timeline"], dest, prod / plan["preview"])
        preview_rel = plan["preview"]
    write_artifact(prod, "sfx_plan.json", {k: v for k, v in plan.items() if k not in {"timeline", "events"}})
    write_audio_fields(prod, plan)
    return {
        "ok": True,
        "dry_run": False,
        "skipped": False,
        "prod": prod.name,
        "episode": episode,
        "duration_sec": plan["duration_sec"],
        "event_count": len(ready),
        "source": plan["source"],
        "audio": plan["audio"],
        "preview": preview_rel,
        "writes_shots_json": False,
        "sfx": snapshot_sfx(prod, episode),
    }
