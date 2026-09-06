#!/usr/bin/env bash
# Turn locked first frames into same-spec clips (slow Ken Burns) so the
# episode can be assembled when Imagine video is unavailable.
set -euo pipefail

frames="${1:?usage: $0 productions/<slug>/04-frames productions/<slug>/05-shots}"
shots="${2:?}"
mkdir -p "$shots"

encode() {
  local src="$1" dest="$2" seconds="$3"
  local frames=$((seconds * 24))
  ffmpeg -y -hide_banner -loglevel error -loop 1 -i "$src" \
    -vf "scale=828:1472,zoompan=z='min(zoom+0.00045,1.07)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=${frames}:s=720x1280:fps=24" \
    -c:v libx264 -pix_fmt yuv420p -r 24 -t "$seconds" -movflags +faststart "$dest"
}

for n in 01 02 03 04 05 06 07 08 09 11 12 13; do
  encode "$frames/SH0${n}.jpg" "$shots/SH0${n}.mp4" 6
  echo "wrote $shots/SH0${n}.mp4"
done
encode "$frames/SH010.jpg" "$shots/SH010.mp4" 10
echo "wrote $shots/SH010.mp4"
