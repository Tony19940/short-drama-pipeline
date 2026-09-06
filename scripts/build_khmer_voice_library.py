#!/usr/bin/env python3
"""Build a reusable Khmer voice library from local dubbed short-drama MP4s.

Run with the live-action dubber venv (Demucs lives there):

  /Users/tony/Documents/高棉配音真人剧/.venv/bin/python \\
    scripts/build_khmer_voice_library.py

Does not process every episode. Each series contributes two 90-second windows.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DUBBER = Path("/Users/tony/Documents/高棉配音真人剧")
if DUBBER.is_dir():
    sys.path.insert(0, str(DUBBER))

SR = 48_000
F0_MALE_MAX = 155.0
F0_FEMALE_MIN = 170.0


def load_sources(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def find_mp4(folder: Path, pattern: str, ep: int) -> Path | None:
    needle = pattern.replace("{n}", str(ep))
    hits = sorted(folder.glob(needle))
    if hits:
        return hits[0]
    numbered = folder / f"{ep}.mp4"
    if numbered.is_file():
        return numbered
    return None


def run(cmd: list[str], label: str) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"{label} failed: {(r.stderr or r.stdout or '')[-800:]}")


def extract_clip(mp4: Path, wav: Path, seconds: int) -> None:
    wav.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", "8", "-t", str(seconds), "-i", str(mp4),
            "-ac", "1", "-ar", str(SR), str(wav),
        ],
        f"ffmpeg {mp4.name}",
    )


def demucs_vocals(mono: Path, work: Path) -> Path:
    existing = list(work.glob("**/vocals.wav"))
    if existing:
        return existing[0]
    try:
        from khmer_dubber.clone_episode_video import run_demucs_two_stems

        stems = run_demucs_two_stems(original_audio=mono, work_dir=work)
        return Path(stems["vocals"])
    except Exception:
        pass
    out = work / "demucs"
    out.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    run(
        [py, "-m", "demucs", "--two-stems=vocals", "-n", "htdemucs", "-o", str(out), str(mono)],
        "demucs",
    )
    hits = list(out.glob("**/vocals.wav"))
    if not hits:
        raise RuntimeError(f"demucs produced no vocals under {out}")
    return hits[0]


def read_wav_f32(path: Path) -> tuple[np.ndarray, int]:
    import wave

    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
        ch = w.getnchannels()
        sw = w.getsampwidth()
    if sw != 2:
        raise RuntimeError(f"need 16-bit wav: {path}")
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, rate


def write_wav_f32(path: Path, audio: np.ndarray, rate: int = SR) -> None:
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(audio, -1, 1) * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def estimate_f0_hz(audio: np.ndarray, rate: int) -> float | None:
    frame = int(rate * 0.04)
    hop = int(rate * 0.02)
    if len(audio) < frame * 2:
        return None
    f0s: list[float] = []
    for i in range(0, len(audio) - frame, hop):
        seg = audio[i : i + frame]
        if float(np.sqrt(np.mean(seg * seg) + 1e-12)) < 0.012:
            continue
        w = seg * np.hanning(len(seg))
        n = 1
        while n < 2 * len(w):
            n *= 2
        spec = np.fft.rfft(w, n=n)
        ac = np.fft.irfft(np.abs(spec) ** 2)[: len(w)]
        minlag = int(rate / 400.0)
        maxlag = min(int(rate / 70.0), len(ac) - 1)
        if maxlag <= minlag:
            continue
        lag = minlag + int(np.argmax(ac[minlag:maxlag]))
        if ac[0] <= 1e-12 or ac[lag] < 0.25 * ac[0]:
            continue
        f0s.append(rate / lag)
    if len(f0s) < 3:
        return None
    return float(np.median(f0s))


def gender_from_f0(f0: float | None) -> str:
    if f0 is None:
        return "unknown"
    if f0 >= F0_FEMALE_MIN:
        return "female"
    if f0 <= F0_MALE_MAX:
        return "male"
    return "ambiguous"


def age_band(gender: str, f0: float | None) -> str:
    if f0 is None:
        return "unknown"
    if gender == "female":
        if f0 >= 205:
            return "young"
        if f0 >= 180:
            return "adult"
        return "mature"
    if gender == "male":
        if f0 >= 140:
            return "young"
        if f0 >= 125:
            return "adult"
        return "mature"
    return "unknown"


def energy_segments(audio: np.ndarray, rate: int) -> list[tuple[int, int]]:
    frame = max(1, int(rate * 0.03))
    hop = max(1, int(rate * 0.01))
    if len(audio) < frame:
        return []
    energies = [
        float(np.sqrt(np.mean(audio[i : i + frame] ** 2) + 1e-12))
        for i in range(0, len(audio) - frame + 1, hop)
    ]
    if not energies:
        return []
    thr = max(0.01, float(np.median(energies)) * 2.5)
    speech = [e > thr for e in energies]
    segs: list[tuple[int, int]] = []
    i = 0
    while i < len(speech):
        if not speech[i]:
            i += 1
            continue
        j = i
        while j < len(speech) and speech[j]:
            j += 1
        start = max(0, i * hop)
        end = min(len(audio), j * hop + frame)
        dur_ms = int((end - start) * 1000 / rate)
        if 600 <= dur_ms <= 8000:
            segs.append((int(start * 1000 / rate), int(end * 1000 / rate)))
        i = j
    return segs


def cluster_embeddings(vectors: list[np.ndarray], sim_thresh: float = 0.55) -> list[int]:
    labels = [-1] * len(vectors)
    centroids: list[np.ndarray] = []
    for i, v in enumerate(vectors):
        v = np.asarray(v, dtype=np.float64).ravel()
        if v.size < 512:
            v = np.pad(v, (0, 512 - int(v.size)))
        else:
            v = v[:512]
        v = v / (np.linalg.norm(v) + 1e-9)
        best_j, best_s = -1, -1.0
        for j, c in enumerate(centroids):
            s = float(np.dot(v, c))
            if s > best_s:
                best_j, best_s = j, s
        if best_j >= 0 and best_s >= sim_thresh and len(centroids) < 10:
            labels[i] = best_j
            c = centroids[best_j] + v
            centroids[best_j] = c / (np.linalg.norm(c) + 1e-9)
        else:
            labels[i] = len(centroids)
            centroids.append(v.copy())
    return labels


def embed_clip(path: Path) -> np.ndarray | None:
    try:
        from khmer_dubber.speaker_embedding import embed_wav

        emb = embed_wav(path, method="speechbrain_ecapa")
        return np.asarray(emb.vector, dtype=np.float64)
    except Exception:
        audio, rate = read_wav_f32(path)
        n = min(len(audio), rate * 2)
        spec = np.abs(np.fft.rfft(audio[:n] * np.hanning(n)))
        spec = spec[:512]
        if len(spec) < 512:
            spec = np.pad(spec, (0, 512 - len(spec)))
        spec = spec / (np.linalg.norm(spec) + 1e-9)
        return spec.astype(np.float64)


def process_mp4(mp4: Path, work: Path, seconds: int, series_id: str, ep: int) -> list[dict]:
    clip = work / "clip.wav"
    if not clip.is_file():
        print(f"  extract {mp4.name}", flush=True)
        extract_clip(mp4, clip, seconds)
    print(f"  demucs {series_id} ep{ep}", flush=True)
    vocals = demucs_vocals(clip, work)
    audio, rate = read_wav_f32(vocals)
    segs = energy_segments(audio, rate)
    out: list[dict] = []
    seg_dir = work / "segments"
    seg_dir.mkdir(exist_ok=True)
    for i, (s_ms, e_ms) in enumerate(segs):
        a0 = int(s_ms * rate / 1000)
        a1 = int(e_ms * rate / 1000)
        clip_a = audio[a0:a1]
        if len(clip_a) < rate * 0.5:
            continue
        sp = seg_dir / f"s{i:04d}.wav"
        if not sp.is_file():
            write_wav_f32(sp, clip_a, rate)
        vec = embed_clip(sp)
        if vec is None:
            continue
        f0 = estimate_f0_hz(clip_a, rate)
        out.append(
            {
                "series": series_id,
                "ep": ep,
                "path": str(sp),
                "start_ms": s_ms,
                "end_ms": e_ms,
                "dur_ms": e_ms - s_ms,
                "vector": vec,
                "f0_hz": f0,
                "gender_guess": gender_from_f0(f0),
            }
        )
    print(f"  segments={len(out)}", flush=True)
    return out


def materialize(vid: str, gender: str, items: list[dict], voices_dir: Path) -> dict | None:
    items = sorted(items, key=lambda x: -x["dur_ms"])
    chosen: list[dict] = []
    acc = 0
    for it in items:
        chosen.append(it)
        acc += it["dur_ms"]
        if acc >= 5000:
            break
    if acc < 2500:
        return None
    vdir = voices_dir / vid
    samples = vdir / "samples"
    if vdir.exists():
        shutil.rmtree(vdir)
    samples.mkdir(parents=True)
    parts: list[np.ndarray] = []
    sample_paths: list[str] = []
    for j, it in enumerate(chosen[:8]):
        src = Path(it["path"])
        dst = samples / f"{j:02d}.wav"
        shutil.copy2(src, dst)
        try:
            sample_paths.append(str(dst.relative_to(voices_dir.parent)))
        except ValueError:
            sample_paths.append(str(dst))
        a, r = read_wav_f32(src)
        parts.append(a)
        parts.append(np.zeros(int(r * 0.08), dtype=np.float32))
    anchor = np.concatenate(parts)
    anchor_path = vdir / "anchor.wav"
    write_wav_f32(anchor_path, anchor, SR)
    f0s = [float(x["f0_hz"]) for x in chosen if x.get("f0_hz") is not None]
    f0 = float(np.median(f0s)) if f0s else None
    band = age_band(gender, f0)
    meta = {
        "voice_id": vid,
        "gender": gender,
        "age_band": band,
        "f0_hz": round(f0, 1) if f0 else None,
        "anchor_ms": int(len(anchor) * 1000 / SR),
        "source_series": sorted({str(x["series"]) for x in chosen}),
        "source_episodes": sorted({int(x["ep"]) for x in chosen}),
        "anchor_path": str(anchor_path),
        "samples": sample_paths,
        "language": "km",
        "suggested_roles": suggest_roles(gender, band),
    }
    (vdir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"  voice {vid} {gender}/{band} f0={meta['f0_hz']} ms={meta['anchor_ms']}", flush=True)
    return meta


def suggest_roles(gender: str, band: str) -> list[str]:
    if gender == "female" and band == "young":
        return ["young_lead", "factory_girl", "sophea", "sara"]
    if gender == "female" and band == "mature":
        return ["elder", "grandmother", "ros", "narrator"]
    if gender == "female":
        return ["adult_female", "narrator", "stepmother"]
    if gender == "male" and band == "mature":
        return ["boss", "father", "piseth"]
    if gender == "male" and band == "young":
        return ["young_male", "lawyer"]
    return ["adult_male", "piseth"]


def build_from_segments(segments: list[dict], lib_root: Path) -> dict:
    voices_dir = lib_root / "voices"
    voices_dir.mkdir(parents=True, exist_ok=True)
    by_series: dict[str, list[dict]] = defaultdict(list)
    for s in segments:
        by_series[str(s["series"])].append(s)

    voices: list[dict] = []
    for series_id, items in sorted(by_series.items()):
        for gender, max_n in (("female", 3), ("male", 3)):
            pool = [x for x in items if x.get("gender_guess") == gender]
            if len(pool) < 2:
                continue
            labels = cluster_embeddings([x["vector"] for x in pool], sim_thresh=0.52)
            clusters: dict[int, list[dict]] = defaultdict(list)
            for x, lab in zip(pool, labels):
                clusters[int(lab)].append(x)
            ranked = sorted(clusters.items(), key=lambda kv: -sum(i["dur_ms"] for i in kv[1]))
            for i, (_lab, cluster_items) in enumerate(ranked[:max_n], start=1):
                vid = f"{series_id}_{gender}_{i:02d}"
                meta = materialize(vid, gender, cluster_items, voices_dir)
                if meta:
                    voices.append(meta)

    catalog = {
        "schema": "khmer_voice_library_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "voice_count": len(voices),
        "male_count": sum(1 for v in voices if v["gender"] == "male"),
        "female_count": sum(1 for v in voices if v["gender"] == "female"),
        "voices": voices,
        "archetypes": pick_archetypes(voices),
        "notes": [
            "跨剧复用。听过再锁到具体角色。",
            "F0 只是粗分年轻/成年/年长，太祖母不一定有同龄真人。",
        ],
    }
    (lib_root / "library.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return catalog


def pick_archetypes(voices: list[dict]) -> dict:
    females = [v for v in voices if v.get("gender") == "female" and v.get("f0_hz")]
    males = [v for v in voices if v.get("gender") == "male" and v.get("f0_hz")]
    # >250 Hz is usually a child; don't auto-cast as 22-year-old lead.
    adult_f = [v for v in females if 175.0 <= float(v["f0_hz"]) <= 245.0]
    pool_f = adult_f or females
    females_hi = sorted(pool_f, key=lambda v: -float(v["f0_hz"]))
    females_lo = sorted(pool_f, key=lambda v: float(v["f0_hz"]))
    males_lo = sorted(males, key=lambda v: float(v["f0_hz"]))
    males_hi = sorted(males, key=lambda v: -float(v["f0_hz"]))
    child_f = [v for v in females if float(v["f0_hz"]) > 245.0]
    young_a = females_hi[0]["voice_id"] if females_hi else None
    young_b = females_hi[1]["voice_id"] if len(females_hi) > 1 else None
    mature = females_lo[0]["voice_id"] if females_lo else None
    used = {young_a, young_b}
    narrator = next((v["voice_id"] for v in females_lo if v["voice_id"] not in used), mature)
    return {
        "young_female_a": young_a,
        "young_female_b": young_b,
        "mature_female": mature,
        "narrator_female": narrator,
        "adult_male": (males_lo[0]["voice_id"] if males_lo else None),
        "young_male": (males_hi[0]["voice_id"] if males_hi else None),
        "child_female": (child_f[0]["voice_id"] if child_f else None),
    }


def seed_from_existing(lib_root: Path) -> int:
    """Copy the already-built 送别/大夏 6-voice bank if wavs are still on disk."""
    old = Path("/Users/tony/Downloads/高棉语配音测试/output/khmer_voice_library/voices")
    if not old.is_dir():
        return 0
    n = 0
    dest = lib_root / "voices"
    dest.mkdir(parents=True, exist_ok=True)
    for src in sorted(old.iterdir()):
        anchor = src / "anchor.wav"
        if not anchor.is_file():
            continue
        vid = f"daxia_seed_{src.name}"
        out = dest / vid
        if out.exists():
            continue
        shutil.copytree(src, out)
        meta_path = out / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        audio, rate = read_wav_f32(out / "anchor.wav")
        f0 = estimate_f0_hz(audio, rate) or meta.get("f0_hz")
        gender = str(meta.get("gender") or gender_from_f0(f0 if f0 is None else float(f0)))
        band = age_band(gender, float(f0) if f0 else None)
        meta.update(
            {
                "voice_id": vid,
                "gender": gender,
                "age_band": band,
                "f0_hz": round(float(f0), 1) if f0 else meta.get("f0_hz"),
                "anchor_path": str(out / "anchor.wav"),
                "source_series": ["daxia"],
                "suggested_roles": suggest_roles(gender, band),
                "seeded_from": str(src),
            }
        )
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        n += 1
        print(f"  seeded {vid}", flush=True)
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--sources",
        default=str(ROOT / "shared/khmer-voices/sources.json"),
    )
    ap.add_argument("--lib-root", default=str(ROOT / "shared/khmer-voices"))
    ap.add_argument("--seed-only", action="store_true", help="only copy the existing 6-voice bank")
    ap.add_argument("--skip-seed", action="store_true")
    args = ap.parse_args()
    lib_root = Path(args.lib_root)
    lib_root.mkdir(parents=True, exist_ok=True)
    work_root = lib_root / "_work"
    work_root.mkdir(exist_ok=True)

    if not args.skip_seed:
        seed_from_existing(lib_root)
    if args.seed_only:
        segs: list[dict] = []
        # rebuild catalog from whatever voices/ already has
        voices = []
        for meta_path in sorted((lib_root / "voices").glob("*/meta.json")):
            voices.append(json.loads(meta_path.read_text(encoding="utf-8")))
        catalog = {
            "schema": "khmer_voice_library_v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "voice_count": len(voices),
            "male_count": sum(1 for v in voices if v.get("gender") == "male"),
            "female_count": sum(1 for v in voices if v.get("gender") == "female"),
            "voices": voices,
            "archetypes": pick_archetypes(voices),
            "notes": ["seeded from existing 送别/大夏 bank; run without --seed-only to add other series"],
        }
        (lib_root / "library.json").write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"SEED voices={len(voices)} → {lib_root}", flush=True)
        return 0

    spec = load_sources(Path(args.sources))
    seconds = int(spec.get("clip_seconds") or 90)
    all_segs: list[dict] = []
    for series in spec.get("series") or []:
        sid = str(series["id"])
        folders = [Path(series["root"])]
        for extra in series.get("also_try") or []:
            folders.append(Path(extra))
        pattern = str(series.get("pattern") or "{n}.mp4")
        for ep in series.get("episodes") or []:
            mp4 = None
            for folder in folders:
                if not folder.is_dir():
                    continue
                mp4 = find_mp4(folder, pattern, int(ep))
                if mp4:
                    break
            if mp4 is None:
                print(f"skip missing {sid} ep{ep}", flush=True)
                continue
            work = work_root / sid / f"ep{int(ep):02d}"
            work.mkdir(parents=True, exist_ok=True)
            print(f"=== {sid} ep{ep} {mp4} ===", flush=True)
            try:
                all_segs.extend(process_mp4(mp4, work, seconds, sid, int(ep)))
            except Exception as exc:
                print(f"  FAIL {sid} ep{ep}: {exc}", flush=True)

    if all_segs:
        build_from_segments(all_segs, lib_root)
    voices = []
    for meta_path in sorted((lib_root / "voices").glob("*/meta.json")):
        voices.append(json.loads(meta_path.read_text(encoding="utf-8")))
    catalog = {
        "schema": "khmer_voice_library_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "voice_count": len(voices),
        "male_count": sum(1 for v in voices if v.get("gender") == "male"),
        "female_count": sum(1 for v in voices if v.get("gender") == "female"),
        "voices": voices,
        "archetypes": pick_archetypes(voices),
        "notes": [
            "跨剧复用。听过再锁到具体角色。",
            "F0 只是粗分年轻/成年/年长，太祖母不一定有同龄真人。",
        ],
    }
    (lib_root / "library.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"DONE voices={catalog['voice_count']} male={catalog['male_count']} "
        f"female={catalog['female_count']} → {lib_root}",
        flush=True,
    )
    return 0 if catalog["voice_count"] >= 4 else 2


if __name__ == "__main__":
    raise SystemExit(main())
