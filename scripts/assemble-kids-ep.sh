#!/usr/bin/env bash
# Ken Burns + Khmer VO + hardsubs → 06-export/ep01.mp4
# Usage: scripts/assemble-kids-ep.sh productions/001-preah-thong-sbai
set -euo pipefail

root="${1:?usage: $0 productions/<slug>}"
frames="$root/04-frames"
narr="$root/07-narration"
shots="$root/05-shots"
out_dir="$root/06-export"
work="$(mktemp -d)"
font="/System/Library/Fonts/Supplemental/Khmer Sangam MN.ttf"
font_zh="/System/Library/Fonts/STHeiti Light.ttc"
[[ -f "$font_zh" ]] || font_zh="/System/Library/Fonts/Hiragino Sans GB.ttc"
[[ -f "$font_zh" ]] || font_zh="$font"

mkdir -p "$shots" "$out_dir"

# Title 2.6s
ffmpeg -y -hide_banner -loglevel error -f lavfi -i "color=c=0x3d2a1e:s=720x1280:d=2.6:r=24" \
  -vf "drawtext=fontfile='${font}':text='រឿងខ្មែរ':fontsize=72:fontcolor=0xf4d58d:x=(w-text_w)/2:y=520,\
drawtext=fontfile='${font}':text='ស្បៃ':fontsize=48:fontcolor=0xfff4e0:x=(w-text_w)/2:y=640" \
  -c:v libx264 -pix_fmt yuv420p -r 24 "$work/title.mp4"

# End 2.2s
ffmpeg -y -hide_banner -loglevel error -f lavfi -i "color=c=0x3d2a1e:s=720x1280:d=2.2:r=24" \
  -vf "drawtext=fontfile='${font}':text='ភាគបន្ទាប់':fontsize=44:fontcolor=0xf4d58d:x=(w-text_w)/2:y=560,\
drawtext=fontfile='${font}':text='ពិធីមង្គលការនៅវាំងនាគ':fontsize=36:fontcolor=0xfff4e0:x=(w-text_w)/2:y=640" \
  -c:v libx264 -pix_fmt yuv420p -r 24 "$work/end.mp4"

python3 - <<PY
import json, subprocess, math
from pathlib import Path
root = Path("$root")
work = Path("$work")
font = "$font"
cues = json.loads((root/"07-narration/cues.json").read_text())["cues"]
list_path = work/"concat.txt"
lines = ["file '%s'" % (work/"title.mp4")]

def probe(p):
    r = subprocess.check_output([
        "ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0", str(p)
    ], text=True).strip()
    return float(r)

for c in cues:
    sid = c["id"]
    img = root/"04-frames"/f"{sid}.jpg"
    wav = root/"07-narration"/f"{sid}.mp3"
    adur = probe(wav)
    dur = max(6.0, adur + 0.7)
    frames = int(round(dur * 24))
    still = work/f"{sid}_still.mp4"
    mixed = work/f"{sid}.mp4"
    # scale then slow zoom
    subprocess.check_call([
        "ffmpeg","-y","-hide_banner","-loglevel","error",
        "-loop","1","-i",str(img),
        "-vf", f"scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,zoompan=z='min(zoom+0.0004,1.06)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=720x1280:fps=24",
        "-c:v","libx264","-pix_fmt","yuv420p","-r","24","-t",f"{dur:.3f}",
        str(still),
    ])
    # escape subtitle
    sub = work/f"{sid}.txt"
    sub.write_text(c["km"], encoding="utf-8")
    subprocess.check_call([
        "ffmpeg","-y","-hide_banner","-loglevel","error",
        "-i",str(still),"-i",str(wav),
        "-filter_complex",
        f"[0:v]drawtext=fontfile='{font}':textfile='{sub}':fontsize=28:fontcolor=white:borderw=3:bordercolor=black@0.7:line_spacing=8:x=(w-text_w)/2:y=h-220[v]",
        "-map","[v]","-map","1:a",
        "-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-ar","48000","-ac","2",
        "-shortest", str(mixed),
    ])
    dest = root/"05-shots"/f"{sid}.mp4"
    dest.write_bytes(mixed.read_bytes())
    lines.append("file '%s'" % mixed)
    print(f"{sid} video={dur:.2f}s vo={adur:.2f}s")

lines.append("file '%s'" % (work/"end.mp4"))
list_path.write_text("\n".join(lines)+"\n")
print("concat list ready")
PY

# title/end need silent audio to concat with aac shots
ffmpeg -y -hide_banner -loglevel error -i "$work/title.mp4" -f lavfi -i anullsrc=r=48000:cl=stereo \
  -c:v copy -c:a aac -shortest "$work/title_a.mp4"
ffmpeg -y -hide_banner -loglevel error -i "$work/end.mp4" -f lavfi -i anullsrc=r=48000:cl=stereo \
  -c:v copy -c:a aac -shortest "$work/end_a.mp4"

python3 - <<PY
from pathlib import Path
p = Path("$work")/"concat.txt"
t = p.read_text()
t = t.replace("title.mp4","title_a.mp4").replace("end.mp4","end_a.mp4")
p.write_text(t)
PY

ffmpeg -y -hide_banner -loglevel error -f concat -safe 0 -i "$work/concat.txt" \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -movflags +faststart \
  "$out_dir/ep01.mp4"

ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$out_dir/ep01.mp4"
echo "wrote $out_dir/ep01.mp4"
rm -rf "$work"
