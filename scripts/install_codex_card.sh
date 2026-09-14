#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
codex_home="${CODEX_HOME:-"$HOME/.codex"}"
dest="${1:-"$codex_home/skills/card"}"
tmp_dest="${dest}.tmp"

if [ -e "$dest" ] && [ "${FORCE:-}" != "1" ]; then
  echo "Refusing to overwrite existing skill: $dest" >&2
  echo "Run with FORCE=1 to replace it, or pass a different destination path." >&2
  exit 1
fi

mkdir -p "$(dirname "$dest")"
rm -rf "$tmp_dest"
cp -R "$repo_root/card" "$tmp_dest"
rm -rf "$dest"
mv "$tmp_dest" "$dest"

echo "Installed card skill to $dest"
echo 'Try: Use $card in Chinese: <paste text here>'

