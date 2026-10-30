#!/usr/bin/env bash
#
# MusicCLI — terminal music player (Linux/macOS launcher)
# Bash counterpart of MusicCLI.bat
#
# Usage:   ./MusicCLI.sh          (or:  bash MusicCLI.sh)
# Needs:   python3, yt-dlp, ffplay on PATH
# Env:     PYTHON     -> python binary to use (default: python3)
#          MUSICCLI_RESULTS -> how many search results to show (default: 25)
#
set -u

# cd to the folder this script lives in, no matter where it's invoked from
cd "$(dirname "${BASH_SOURCE[0]}")" || {
    echo "MusicCLI: cannot cd to script directory" >&2
    exit 1
}

# mirror .bat's `chcp 65001` — force UTF-8 output so ♪/accented titles render
export PYTHONIOENCODING=utf-8
export PYTHONUNBUFFERED=1

# mirror .bat's `title MusicCLI` — set the terminal window/tab title
printf '\033]0;MusicCLI\007'

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "MusicCLI: '$PY' not found on PATH (install Python 3 or set PYTHON)" >&2
    echo "MusicCLI: press Enter to close..." >&2
    read -r _ 2>/dev/null || true
    exit 1
fi

command -v yt-dlp >/dev/null 2>&1 \
    || echo "MusicCLI: warning - 'yt-dlp' not found; search/playback will fail" >&2
command -v ffplay >/dev/null 2>&1 \
    || echo "MusicCLI: warning - 'ffplay' not found; playback will fail" >&2

"$PY" -u musiccli.py
rc=$?

# mirror .bat's `pause` so the window stays open when it exits unexpectedly
if [ "$rc" -ne 0 ] && [ -t 0 ]; then
    echo "MusicCLI: exited with code $rc. Press Enter to close..."
    read -r _ 2>/dev/null || true
fi

exit "$rc"
