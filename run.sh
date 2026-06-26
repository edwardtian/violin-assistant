#!/bin/bash
cd "$(dirname "$0")"
# Find portaudio library path (needed for sounddevice)
export LD_LIBRARY_PATH="/home/tianye/miniconda3/envs/hy3d/lib:$LD_LIBRARY_PATH"
# Use Wayland if available (suppresses the XDG_SESSION_TYPE warning)
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-wayland}"
.venv/bin/python3 main.py
