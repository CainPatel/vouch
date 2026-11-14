#!/usr/bin/env bash
set -euo pipefail

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is not installed; skipping automatic rough cut."
  exit 0
fi

echo "[make_demo_video] Recording 1920x1080 Playwright hero run and timestamped audio..."
uv run python scripts/record_rough_cut.py

mkdir -p artifacts
ffmpeg -y \
  -i .tmp/rough_cut_video/raw_demo.webm \
  -i .tmp/rough_cut_video/mixed_audio.wav \
  -t 58 \
  -c:v libx264 \
  -preset fast \
  -crf 21 \
  -pix_fmt yuv420p \
  -c:a aac \
  -b:a 160k \
  -shortest \
  artifacts/demo_auto.mp4

echo "[make_demo_video] Wrote artifacts/demo_auto.mp4"
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 artifacts/demo_auto.mp4 | awk '{printf "[make_demo_video] Duration: %.2fs\n", $1}'
