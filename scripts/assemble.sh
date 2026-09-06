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

kb="$(find "$shots" -maxdepth 1 \( -name '*kenburns*.mp4' -o -name '*still-pass*.mp4' \) -print -quit || true)"
if [[ -n "$kb" ]]; then
  echo "Ken Burns / still-pass files cannot enter 06-export" >&2
  exit 1
fi

for f in "$shots"/SH*.mp4; do
  printf "file '%s'\n" "$(cd "$(dirname "$f")" && pwd)/$(basename "$f")" >>"$list"
done

ffmpeg -y -f concat -safe 0 -i "$list" -c copy "$out"
rm -f "$list"
echo "wrote $out"
