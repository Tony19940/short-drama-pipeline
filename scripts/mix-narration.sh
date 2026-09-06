#!/usr/bin/env bash
# Overlay per-shot narration onto 05-shots, concat into 06-export/epXX.mp4
# Usage: scripts/mix-narration.sh productions/<slug> [epNN]
set -euo pipefail

root="${1:?usage: $0 productions/<slug> [epNN]}"
ep="${2:-ep01}"
shots="$root/05-shots"
narr="$root/07-narration"
out_dir="$root/06-export"
work="$(mktemp -d)"
list="$work/concat.txt"
mkdir -p "$out_dir"

if ! ls "$shots"/SH*.mp4 >/dev/null 2>&1; then
  echo "no SH*.mp4 in $shots" >&2
  exit 1
fi

for video in "$shots"/SH*.mp4; do
  base="$(basename "$video" .mp4)"
  wav="$narr/${base}.wav"
  mixed="$work/${base}.mp4"
  if [[ -f "$wav" ]]; then
    vdur="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$video")"
    adur="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$wav")"
    # If narration is longer, freeze-last-frame the video to match. Never speed up voice.
    awk_cmp="$(awk -v a="$adur" -v v="$vdur" 'BEGIN { print (a > v + 0.05) ? 1 : 0 }')"
    if [[ "$awk_cmp" == 1 ]]; then
      ffmpeg -y -hide_banner -loglevel error \
        -i "$video" -i "$wav" \
        -filter_complex "[0:v]tpad=stop_mode=clone:stop_duration=$(awk -v a="$adur" -v v="$vdur" 'BEGIN { printf "%.3f", a - v }')[v]" \
        -map "[v]" -map 1:a -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "$mixed"
    else
      ffmpeg -y -hide_banner -loglevel error \
        -i "$video" -i "$wav" \
        -map 0:v -map 1:a -c:v copy -c:a aac -shortest "$mixed"
    fi
  else
    echo "warn: missing $wav, using silent video" >&2
    ffmpeg -y -hide_banner -loglevel error \
      -i "$video" -f lavfi -i anullsrc=r=48000:cl=mono \
      -map 0:v -map 1:a -c:v copy -c:a aac -shortest "$mixed"
  fi
  printf "file '%s'\n" "$mixed" >>"$list"
done

ffmpeg -y -f concat -safe 0 -i "$list" -c copy "$out_dir/${ep}.mp4"
rm -rf "$work"
echo "wrote $out_dir/${ep}.mp4"
