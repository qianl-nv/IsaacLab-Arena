#!/bin/bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "usage: $0 /results/images/name.png" >&2
    exit 2
fi

output=$1
mkdir -p "$(dirname "$output")"

ffmpeg -hide_banner -loglevel error -y \
    -f x11grab -video_size 1920x1080 -i "${DISPLAY:-:1}+0,0" \
    -frames:v 1 "$output"
test -s "$output"
echo "$output"
