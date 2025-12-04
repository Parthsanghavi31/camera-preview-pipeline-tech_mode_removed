#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
watch -n 0.5 -t "eval 'echo \"Service Version: \$(cat \"${SCRIPT_DIR}/../version.txt\")\"'; echo '---------------------------------------'; sudo systemctl status camera-preview.service | tail -n +1"

