#!/usr/bin/env bash
# Concat shots in a production's 05-shots/ into 06-export/ep01.mp4
# Usage: scripts/assemble.sh productions/001-wip
set -euo pipefail

root="${1:?usage: $0 productions/<slug> [video-dir] [outfile]}"
shots="$root/${2:-05-shots}"
out="$root/${3:-06-export/ep01.mp4}"
mkdir -p "$(dirname "$out")"
list="$(mktemp)"

if ! ls "$shots"/SH*.mp4 >/dev/null 2>&1; then
  echo "no SH*.mp4 in $shots" >&2
  exit 1
fi

case "$shots" in
  *03-storyboard/animatic*)
    echo "03-storyboard/animatic is a review animatic, not shots; it cannot enter 06-export" >&2
    exit 1
    ;;
esac

kb="$(find "$shots" -maxdepth 1 \( -name '*kenburns*.mp4' -o -name '*still-pass*.mp4' -o -name '*animatic*.mp4' \) -print -quit || true)"
if [[ -n "$kb" ]]; then
  echo "Ken Burns / still-pass / animatic files cannot enter 06-export" >&2
  exit 1
fi

# Official clips are already 1280x720 (Seedance Mini 720p, or H3 768p locally
# scaled). -c copy cannot mix sizes. Refuse if SH*.mp4 at this folder disagree.
sizes=""
for f in "$shots"/SH*.mp4; do
  printf "file '%s'\n" "$(cd "$(dirname "$f")" && pwd)/$(basename "$f")" >>"$list"
  if command -v ffprobe >/dev/null 2>&1; then
    size="$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0:s=x "$f" || true)"
    if [[ -n "$size" ]]; then
      if [[ -z "$sizes" ]]; then
        sizes="$size"
      elif [[ "$size" != "$sizes" ]]; then
        echo "mixed shot sizes ($sizes vs $size); cannot -c copy. Official 05-shots must already be the same size (1280x720 for 16:9 EP)." >&2
        rm -f "$list"
        exit 1
      fi
    fi
  fi
done

ffmpeg -y -f concat -safe 0 -i "$list" -c copy "$out"
rm -f "$list"
echo "wrote $out"
