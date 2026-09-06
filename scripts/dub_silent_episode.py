#!/usr/bin/env python3
"""Gate F: clone Khmer onto a finished silent AI picture.

Skip diarization. Skip original-vocal extract. Speaker ids come from cues.json.

  python3 scripts/dub_silent_episode.py --prod productions/004-yuye-jinlian --dry-run
  python3 scripts/dub_silent_episode.py --prod productions/004-yuye-jinlian
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_path(needle: str) -> Path | None:
    p = Path(needle)
    if p.is_file():
        return p
    rel = (ROOT / needle).resolve()
    if rel.is_file():
        return rel
    return None


def resolve_anchor(voice_id: str | None, voices_map: dict, lib: dict) -> Path | None:
    if not voice_id:
        return None
    slot = None
    for row in voices_map.get("slots") or []:
        if row.get("speaker_id") == voice_id or row.get("voice_id") == voice_id:
            slot = row
            break
    explicit = None
    if slot:
        explicit = slot.get("reference_wav") or slot.get("voice_id")
    needle = str(explicit or voice_id)
    found = resolve_path(needle)
    if found is not None:
        return found
    for v in lib.get("voices") or []:
        if v.get("voice_id") == needle:
            ap = Path(str(v.get("anchor_path") or ""))
            if ap.is_file():
                return ap
    arch = (lib.get("archetypes") or {}).get(needle)
    if arch:
        return resolve_anchor(str(arch), {"slots": []}, lib)
    return None


def clone_one(*, url: str, text: str, reference: Path, api_key: str, timeout: int, seed: int = 42) -> bytes:
    boundary = "----DubBoundary"
    with reference.open("rb") as fh:
        ref_bytes = fh.read()
    parts = []

    def field(name: str, value: str) -> None:
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(value.encode("utf-8") + b"\r\n")

    field("text", text)
    field("language_id", "km")
    field("speed", "1.0")
    field("seed", str(int(seed)))
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        b'Content-Disposition: form-data; name="reference"; filename="anchor.wav"\r\n'
        b"Content-Type: audio/wav\r\n\r\n"
    )
    parts.append(ref_bytes + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/clone",
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"clone HTTP {exc.code}: {exc.read()[:400]!r}") from exc
    if "audio" in ctype and "json" not in ctype:
        return raw
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return raw
    audio_url = payload.get("audio_url") or payload.get("url")
    if audio_url:
        with urllib.request.urlopen(audio_url, timeout=timeout) as resp:
            return resp.read()
    b64 = payload.get("audio_base64")
    if b64:
        import base64

        return base64.b64decode(b64)
    raise SystemExit(f"clone returned no audio: {payload}")


def mix(video: Path, clips: list[tuple[int, Path]], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not clips:
        raise SystemExit("no dubbed clips to mix")
    cmd = ["ffmpeg", "-y", "-i", str(video)]
    for _start, wav in clips:
        cmd += ["-i", str(wav)]
    n = len(clips)
    delays = []
    for i, (start_ms, _) in enumerate(clips, start=1):
        delays.append(f"[{i}:a]adelay={start_ms}|{start_ms},aformat=sample_rates=48000:channel_layouts=stereo[a{i}]")
    mix_in = "".join(f"[a{i}]" for i in range(1, n + 1))
    filt = ";".join(delays) + f";{mix_in}amix=inputs={n}:normalize=0:dropout_transition=0[vo]"
    cmd += [
        "-filter_complex", filt,
        "-map", "0:v",
        "-map", "[vo]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(dest),
    ]
    subprocess.check_call(cmd)


def mix_timeline(clips: list[tuple[int, Path]], dest: Path, duration_ms: int) -> None:
    """Lay cloned cues onto a silent bed of episode length. Does not touch picture."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not clips:
        raise SystemExit("no dubbed clips to mix")
    duration_s = max(0.1, duration_ms / 1000.0)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={duration_s:.3f}",
    ]
    for _start, wav in clips:
        cmd += ["-i", str(wav)]
    n = len(clips)
    delays = []
    for i, (start_ms, _) in enumerate(clips, start=1):
        delays.append(
            f"[{i}:a]aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo,"
            f"adelay={start_ms}|{start_ms}[a{i}]"
        )
    mix_in = "".join(f"[a{i}]" for i in range(1, n + 1))
    filt = (
        ";".join(delays)
        + f";[0:a]{mix_in}amix=inputs={n + 1}:normalize=0:dropout_transition=0:duration=first[vo]"
    )
    cmd += [
        "-filter_complex", filt,
        "-map", "[vo]",
        "-c:a", "pcm_s16le",
        "-t", f"{duration_s:.3f}",
        str(dest),
    ]
    subprocess.check_call(cmd)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--prod", required=True)
    p.add_argument("--cues", help="default <prod>/07-dubbing/ep01.cues.json")
    p.add_argument("--video", help="default <prod>/06-export/ep01.mp4")
    p.add_argument("--library", default=str(ROOT / "shared/khmer-voices/library.json"))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--audio-only",
        action="store_true",
        help="只出 64 秒高棉语音轨 wav，不烧进画面、不碰原片声",
    )
    args = p.parse_args()

    prod = Path(args.prod).resolve()
    cues_path = Path(args.cues).resolve() if args.cues else prod / "07-dubbing" / "ep01.cues.json"
    video = Path(args.video).resolve() if args.video else prod / "06-export" / "ep01.mp4"
    voices_map = load_json(prod / "07-dubbing" / "voices.json")
    lib = load_json(Path(args.library)) if Path(args.library).is_file() else {"voices": [], "archetypes": {}}
    data = load_json(cues_path)
    work = prod / "07-dubbing" / "work"
    work.mkdir(parents=True, exist_ok=True)

    plan = []
    missing = []
    for cue in data.get("cues") or []:
        km = str(cue.get("text_km") or "").strip()
        if not km:
            missing.append(f"{cue.get('id')} has no text_km")
            continue
        sid = str(cue.get("speaker_id") or "")
        slot = next((s for s in voices_map.get("slots") or [] if s.get("speaker_id") == sid), {})
        voice_id = slot.get("voice_id") or (lib.get("archetypes") or {}).get(
            {
                "narrator": "narrator_female",
                "sophea": "young_female_a",
                "sara": "young_female_b",
                "ros": "mature_female",
                "piseth": "adult_male",
            }.get(sid, "")
        )
        anchor = resolve_anchor(sid, voices_map, lib) or resolve_anchor(str(voice_id or ""), voices_map, lib)
        seed = int(slot.get("seed") or 42)
        if anchor is None:
            missing.append(f"{sid}: no library_anchor (voice_id={voice_id!r})")
        plan.append(
            {
                "id": cue.get("id"),
                "speaker_id": sid,
                "start_ms": int(cue["start_ms"]),
                "end_ms": int(cue["end_ms"]),
                "text_km": km,
                "voice_id": voice_id,
                "anchor": str(anchor) if anchor else None,
                "seed": seed,
                "line_kind": cue.get("line_kind"),
            }
        )

    (work / "plan.json").write_text(
        json.dumps({"video": str(video), "cues": plan, "missing": missing}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {work / 'plan.json'}  cues={len(plan)}")
    for row in missing:
        print("  missing:", row)
    if args.dry_run:
        return
    if missing:
        raise SystemExit("声音库还没对上角色，先填 07-dubbing/voices.json")
    if not args.audio_only and not video.is_file():
        raise SystemExit(f"画面还没有：{video}\n先出完片再贴配音，或加 --audio-only 只出 wav。")
    clone_url = os.environ.get("KHMER_CLONE_CLOUD_URL", "").strip()
    if not clone_url:
        raise SystemExit("没有 KHMER_CLONE_CLOUD_URL。克隆服务起来后再跑，不要改用别的 TTS。")
    api_key = os.environ.get("KHMER_CLONE_CLOUD_API_KEY", "").strip()
    clips: list[tuple[int, Path]] = []
    for row in plan:
        wav = work / f"{row['id']}.wav"
        print(f"clone {row['id']} {row['speaker_id']} {Path(row['anchor']).parent.name} seed={row['seed']} …", flush=True)
        audio = clone_one(
            url=clone_url,
            text=row["text_km"],
            reference=Path(row["anchor"]),
            api_key=api_key,
            timeout=600,
            seed=int(row["seed"]),
        )
        wav.write_bytes(audio)
        clips.append((int(row["start_ms"]), wav))
        time.sleep(0.2)
    duration_ms = int(data.get("duration_ms") or (plan[-1]["end_ms"] if plan else 0))
    wav_dest = work / "ep01.km.wav"
    mix_timeline(clips, wav_dest, duration_ms)
    print(f"wrote {wav_dest}")
    if args.audio_only:
        return
    dest = prod / "06-export" / "ep01.km-dub.mp4"
    mix(video, clips, dest)
    print(f"wrote {dest}")


if __name__ == "__main__":
    main()
