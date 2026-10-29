#!/bin/bash
set -eu
# Existing services are preserved. No instance resize or paid AWS resources.
sudo dnf install -y python3.11 python3.11-pip dejavu-sans-fonts
mkdir -p "$HOME/cyber-quiz" "$HOME/.config/cyber-quiz"
chmod 700 "$HOME/.config/cyber-quiz"
cd "$HOME/cyber-quiz"
python3.11 -m venv .venv
.venv/bin/pip install --no-cache-dir -r requirements.txt imageio-ffmpeg
.venv/bin/python - <<'PY'
import imageio_ffmpeg,pathlib
p=pathlib.Path('.venv/bin/ffmpeg')
if not p.exists():p.symlink_to(imageio_ffmpeg.get_ffmpeg_exe())
PY
