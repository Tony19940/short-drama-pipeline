#!/usr/bin/env python3
"""Series-wide kids story BGM + small SFX kit. No numpy."""
from __future__ import annotations

import math
import struct
import subprocess
import wave
from pathlib import Path

SR = 44100
ROOT = Path("/Users/tony/vibe coding/short-drama-pipeline/productions/khmer-stories/shared/audio")


def clamp(x: float) -> float:
    return max(-1.0, min(1.0, x))


def write_wav(path: Path, samples: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        buf = bytearray()
        for s in samples:
            v = int(clamp(s) * 30000)
            buf += struct.pack("<hh", v, v)
        w.writeframes(buf)


def env(i: int, n: int, a=0.02, r=0.35) -> float:
    t = i / n if n else 0
    if t < a:
        return t / a
    if t > 1 - r:
        return max(0.0, (1 - t) / r)
    return 1.0


def tone(freq: float, dur: float, vol=0.12, a=0.02, r=0.4) -> list[float]:
    n = int(dur * SR)
    out = []
    for i in range(n):
        t = i / SR
        # soft triangle-ish (less harsh than square, warmer than pure sine)
        s = math.sin(2 * math.pi * freq * t)
        s += 0.22 * math.sin(2 * math.pi * freq * 2 * t)
        s += 0.08 * math.sin(2 * math.pi * freq * 3 * t)
        out.append(s * vol * env(i, n, a, r))
    return out


def mix_at(bed: list[float], clip: list[float], at: float) -> None:
    start = int(at * SR)
    if start + len(clip) > len(bed):
        bed.extend([0.0] * (start + len(clip) - len(bed)))
    for i, s in enumerate(clip):
        bed[start + i] += s


def make_bed(path: Path, seconds: float = 90.0) -> None:
    # Slow pentatonic in G, harp-like. Kids story, not a pop loop.
    # G3 A3 B3 D4 E4 G4
    notes = [
        (196.00, 1.8), (220.00, 1.6), (246.94, 1.8), (293.66, 2.2),
        (329.63, 1.8), (293.66, 1.6), (246.94, 2.0), (220.00, 1.8),
        (196.00, 2.4), (246.94, 1.6), (293.66, 2.0), (392.00, 2.4),
        (329.63, 2.0), (293.66, 1.8), (246.94, 2.2), (196.00, 2.8),
    ]
    bed = [0.0] * int(seconds * SR)
    t = 0.4
    # quiet fifth pad under the whole thing
    pad = tone(98.00, seconds, vol=0.028, a=1.2, r=2.0)
    mix_at(bed, pad, 0)
    pad2 = tone(146.83, seconds, vol=0.018, a=1.6, r=2.0)
    mix_at(bed, pad2, 0)
    while t < seconds - 4:
        for freq, dur in notes:
            if t >= seconds - 3:
                break
            mix_at(bed, tone(freq, dur, vol=0.07, a=0.03, r=0.55), t)
            # light upper octave echo
            mix_at(bed, tone(freq * 2, dur * 0.7, vol=0.018, a=0.04, r=0.6), t + 0.12)
            t += dur * 0.92
    # fade tail
    fade = int(2.5 * SR)
    for i in range(fade):
        bed[-1 - i] *= i / fade
    write_wav(path, bed)


def make_chime(path: Path) -> None:
    s: list[float] = []
    for f, d, v in ((523.25, 0.9, 0.11), (659.25, 1.0, 0.09), (783.99, 1.3, 0.07)):
        clip = tone(f, d, vol=v, a=0.005, r=0.7)
        if not s:
            s = clip
        else:
            mix_at(s, clip, 0.08)
    write_wav(path, s)


def lavfi(path: Path, expr: str, extra: list[str] | None = None) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", expr]
    if extra:
        cmd += extra
    cmd += [str(path)]
    subprocess.check_call(cmd)


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    make_bed(ROOT / "story-bed.wav", 96)
    make_chime(ROOT / "chime-soft.wav")
    # sea bed — pink noise, very low, loopable
    lavfi(
        ROOT / "sea-loop.wav",
        "anoisesrc=color=pink:d=16:r=44100",
        ["-af", "lowpass=f=520,highpass=f=80,volume=0.22,afade=t=in:d=0.8,afade=t=out:st=15.2:d=0.8"],
    )
    # ankle wave
    lavfi(
        ROOT / "wave-soft.wav",
        "anoisesrc=color=pink:d=1.6:r=44100",
        ["-af", "lowpass=f=900,highpass=f=200,volume=0.45,afade=t=in:d=0.12,afade=t=out:st=0.7:d=0.9"],
    )
    # splash into water
    lavfi(
        ROOT / "splash.wav",
        "anoisesrc=color=white:d=0.7:r=44100",
        ["-af", "bandpass=f=1200:width_type=h:w=800,volume=0.5,afade=t=in:d=0.02,afade=t=out:st=0.15:d=0.5"],
    )
    # wood boat
    lavfi(
        ROOT / "wood.wav",
        "sine=f=180:d=0.18",
        ["-af", "volume=0.25,afade=t=out:d=0.16"],
    )
    # sip / drink
    lavfi(
        ROOT / "sip.wav",
        "anoisesrc=color=brown:d=0.45:r=44100",
        ["-af", "lowpass=f=400,volume=0.4,afade=t=in:d=0.05,afade=t=out:st=0.2:d=0.25"],
    )
    # wet steps
    lavfi(
        ROOT / "steps.wav",
        "anoisesrc=color=brown:d=1.1:r=44100",
        ["-af", "lowpass=f=280,volume=0.35,afade=t=in:d=0.04,afade=t=out:st=0.8:d=0.3"],
    )
    print("wrote", ROOT)


if __name__ == "__main__":
    main()
