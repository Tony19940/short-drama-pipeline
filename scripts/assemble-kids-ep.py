#!/usr/bin/env python3
"""Ken Burns + Khmer VO + PNG hardsubs → 06-export/ep01.mp4"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

W, H, FPS = 720, 1280, 24
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
AUDIO_KIT = Path("/Users/tony/vibe coding/short-drama-pipeline/productions/khmer-stories/shared/audio")


def run(cmd: list[str], quiet: bool = False) -> None:
    kw = {}
    if quiet:
        kw["stdout"] = subprocess.DEVNULL
        kw["stderr"] = subprocess.DEVNULL
    subprocess.check_call(cmd, **kw)


def probe(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        text=True,
    ).strip()
    return float(out)


def chrome_shot(html: Path, dest: Path) -> None:
    run(
        [
            str(CHROME),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--allow-file-access-from-files",
            "--force-device-scale-factor=1",
            f"--window-size={W},{H}",
            f"--screenshot={dest}",
            html.resolve().as_uri(),
        ],
        quiet=True,
    )


def write_html(path: Path, body: str) -> None:
    path.write_text(
        """<!doctype html><html lang="km"><meta charset="utf-8">
<style>
html,body{margin:0;width:720px;height:1280px;overflow:hidden;
  font-family:"Khmer MN","Khmer Sangam MN",sans-serif;}
.card{width:720px;height:1280px;background:#3d2a1e;display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:28px;text-align:center;padding:40px;box-sizing:border-box}
.gold{font-size:68px;color:#f4d58d;line-height:1.35}
.cream{font-size:40px;color:#fff4e0;line-height:1.4}
.frame{position:relative;width:720px;height:1280px;background:#1a120c}
.frame img{position:absolute;inset:0;width:720px;height:1280px;object-fit:cover}
.sub{position:absolute;left:36px;right:36px;bottom:150px;background:rgba(0,0,0,.55);
  color:#fff;font-size:30px;line-height:1.45;text-align:center;padding:14px 16px;border-radius:14px}
</style>
"""
        + body,
        encoding="utf-8",
    )


def card(path: Path, title: str, subtitle: str) -> None:
    html = path.with_suffix(".html")
    write_html(
        html,
        f'<div class="card"><div class="gold">{title}</div><div class="cream">{subtitle}</div></div>',
    )
    chrome_shot(html, path)


def framed_still(bg: Path, text: str, dest: Path) -> None:
    html = dest.with_suffix(".html")
    write_html(
        html,
        f'<div class="frame"><img src="{bg.resolve().as_uri()}" alt=""><div class="sub">{text}</div></div>',
    )
    chrome_shot(html, dest)


def still_hold(src: Path, dest: Path, seconds: float) -> None:
    """Stable still. No zoompan — that filter jitters and feels uneasy."""
    run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-loop", "1", "-i", str(src),
            "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS), "-t", f"{seconds:.3f}",
            str(dest),
        ]
    )


def xfade_videos(clips: list[Path], dest: Path, fade: float = 0.5) -> None:
    if len(clips) == 1:
        shutil.copy2(clips[0], dest)
        return
    durs = [probe(p) for p in clips]
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for p in clips:
        cmd += ["-i", str(p)]
    parts = []
    last = "[0:v]"
    acc = durs[0]
    for i in range(1, len(clips)):
        offset = acc - fade
        out = f"[v{i}]" if i < len(clips) - 1 else "[vout]"
        parts.append(f"{last}[{i}:v]xfade=transition=fade:duration={fade}:offset={offset:.3f}{out}")
        last = out
        acc = acc + durs[i] - fade
    cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest)]
    run(cmd)


def concat_audio(clips: list[Path], dest: Path, fade: float = 0.5) -> None:
    if len(clips) == 1:
        shutil.copy2(clips[0], dest)
        return
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for p in clips:
        cmd += ["-i", str(p)]
    parts = []
    last = "[0:a]"
    for i in range(1, len(clips)):
        out = f"[a{i}]" if i < len(clips) - 1 else "[aout]"
        parts.append(f"{last}[{i}:a]acrossfade=d={fade}:c1=tri:c2=tri{out}")
        last = out
    cmd += ["-filter_complex", ";".join(parts), "-map", "[aout]", "-c:a", "aac", "-ar", "48000", "-ac", "2", str(dest)]
    run(cmd)


def still_color(src: Path, dest: Path, seconds: float) -> None:
    run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-loop", "1", "-i", str(src),
            "-vf", f"scale={W}:{H}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS), "-t", f"{seconds:.3f}",
            str(dest),
        ]
    )


def overlay_sub(video: Path, png: Path, dest: Path) -> None:
    run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video), "-i", str(png),
            "-filter_complex", "[0:v][1:v]overlay=0:0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
            str(dest),
        ]
    )


def mix_audio(video: Path, audio: Path | None, dest: Path, seconds: float) -> None:
    if audio is None:
        run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(video), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-ac", "2",
                "-t", f"{seconds:.3f}", str(dest),
            ]
        )
        return
    run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video), "-i", str(audio),
            "-filter_complex", "[1:a]apad=pad_dur=10[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-ac", "2",
            "-t", f"{seconds:.3f}", str(dest),
        ]
    )


def synth_full(text: str, voice: str, dest: Path, rate: str = "-12%") -> None:
    import asyncio
    import edge_tts

    async def go() -> None:
        comm = edge_tts.Communicate(text, voice, rate=rate)
        await comm.save(str(dest))

    asyncio.run(go())


def mix_story_audio(
    dest: Path,
    vo: Path,
    vo_delay: float,
    video_dur: float,
    sfx_events: list[dict],
    kit: Path,
) -> None:
    bed = kit / "story-bed.wav"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(vo),
        "-stream_loop", "-1", "-i", str(bed),
    ]
    # inputs: 0=vo 1=bgm 2...=sfx
    sfx_inputs = []
    for ev in sfx_events:
        src = kit / ev["file"]
        if ev.get("loop"):
            cmd += ["-stream_loop", "-1"]
        cmd += ["-i", str(src)]
        sfx_inputs.append(ev)

    fade_out_at = max(0.2, video_dur - 2.4)
    vo_ms = int(vo_delay * 1000)
    filters = [
        f"[0:a]adelay={vo_ms}|{vo_ms},apad=pad_dur=2,atrim=0:{video_dur:.3f},volume=1.05[vo]",
        f"[1:a]atrim=0:{video_dur:.3f},volume=0.13,afade=t=in:d=1.6,afade=t=out:st={fade_out_at:.3f}:d=2.3[bgm]",
    ]
    mix_names = ["[vo]", "[bgm]"]
    for i, ev in enumerate(sfx_inputs):
        idx = i + 2
        delay = int(ev["at"] * 1000)
        vol = ev.get("vol", 0.35)
        if ev.get("loop"):
            dur = ev.get("dur", 8.0)
            filters.append(
                f"[{idx}:a]atrim=0:{dur:.3f},apad=whole_dur={dur:.3f},"
                f"adelay={delay}|{delay},volume={vol},afade=t=in:d=0.7,afade=t=out:st={max(0.2, dur-1.4):.3f}:d=1.3[s{i}]"
            )
        else:
            filters.append(f"[{idx}:a]adelay={delay}|{delay},volume={vol}[s{i}]")
        mix_names.append(f"[s{i}]")
    n = len(mix_names)
    filters.append(
        "".join(mix_names)
        + f"amix=inputs={n}:duration=longest:dropout_transition=0:normalize=0,"
        + f"alimiter=limit=0.95,atrim=0:{video_dur:.3f}[a]"
    )
    cmd += ["-filter_complex", ";".join(filters), "-map", "[a]", "-c:a", "aac", "-ar", "48000", "-ac", "2", str(dest)]
    run(cmd)


def main() -> None:
    import sys

    root = Path(sys.argv[1]).resolve()
    frames = root / "04-frames"
    narr = root / "07-narration"
    shots = root / "05-shots"
    out = root / "06-export"
    shots.mkdir(exist_ok=True)
    out.mkdir(exist_ok=True)
    spec = json.loads((narr / "cues.json").read_text())
    cues = spec["cues"]
    voice = spec.get("voice", "km-KH-SreymomNeural")
    full_km = spec.get("full_km") or " ".join(c["km"] for c in cues)
    sfx_spec = []
    sfx_path = narr / "sfx.json"
    if sfx_path.exists():
        sfx_spec = json.loads(sfx_path.read_text())

    full_mp3 = narr / "full.mp3"
    synth_full(full_km, voice, full_mp3)
    vo_dur = probe(full_mp3)
    weights = [max(len(c["km"]), 8) for c in cues]
    wsum = sum(weights)
    holds = [max(3.4, vo_dur * (w / wsum)) for w in weights]

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        fade = 0.5
        title_hold = 2.4
        end_hold = 2.2
        card(td / "title.png", "រឿងខ្មែរ", "ស្បៃ")
        card(td / "end.png", "ភាគបន្ទាប់", "ពិធីមង្គលការនៅវាំងនាគ")

        vclips: list[Path] = []
        still_color(td / "title.png", td / "title.mp4", title_hold + fade)
        vclips.append(td / "title.mp4")

        # picture starts when VO starts (after title)
        t = 0.0
        starts = {}
        for c, hold in zip(cues, holds):
            starts[c["id"]] = t
            still = td / f"{c['id']}.png"
            vis = td / f"{c['id']}.mp4"
            framed_still(frames / f"{c['id']}.jpg", c["km"], still)
            still_hold(still, vis, hold + fade)
            shutil.copy2(vis, shots / f"{c['id']}.mp4")
            vclips.append(vis)
            print(f"{c['id']} hold={hold:.2f}s at={title_hold + t:.2f}s")
            t += hold

        still_color(td / "end.png", td / "end.mp4", end_hold + fade)
        vclips.append(td / "end.mp4")

        xfade_videos(vclips, td / "video.mp4", fade=fade)
        video_dur = probe(td / "video.mp4")

        events = []
        id_to_until = {c["id"]: i for i, c in enumerate(cues)}
        for ev in sfx_spec:
            shot = ev["shot"]
            at = title_hold + starts[shot] + ev.get("delay", 0)
            item = {"file": ev["file"], "at": at, "vol": ev.get("vol", 0.35), "loop": ev.get("loop", False)}
            if ev.get("loop") and ev.get("until"):
                end_id = ev["until"]
                end_t = title_hold + starts[end_id]
                item["dur"] = max(1.0, end_t - at)
            elif ev.get("loop"):
                item["dur"] = max(1.0, title_hold + vo_dur - at)
            events.append(item)

        mix_story_audio(td / "mix.m4a", full_mp3, title_hold, video_dur, events, AUDIO_KIT)
        final = out / "ep01.mp4"
        run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(td / "video.mp4"), "-i", str(td / "mix.m4a"),
                "-c:v", "copy", "-c:a", "aac", "-shortest",
                "-movflags", "+faststart", str(final),
            ]
        )
        print("vo", vo_dur, "video", probe(final))
        print("wrote", final)


if __name__ == "__main__":
    main()
