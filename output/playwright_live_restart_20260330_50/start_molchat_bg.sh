#!/usr/bin/env bash
set -euo pipefail

source ~/.nvm/nvm.sh
nvm use 24 >/dev/null

exec bash /mnt/c/Users/user/Desktop/molcaht/molchat/v3/start-molchat.sh
