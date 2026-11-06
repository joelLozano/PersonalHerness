#!/usr/bin/env bash
# Instala el CLI `agentes` de forma global (aislado) a partir de este repositorio.
#   ./install.sh            -> con base vectorial (chromadb)
#   ./install.sh --lite     -> sin chromadb (solo búsqueda BM25, más ligero)
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPEC="$DIR[vector]"
[[ "${1:-}" == "--lite" ]] && SPEC="$DIR"

if command -v uv >/dev/null 2>&1; then
  uv tool install --force --editable "$SPEC" --python 3.12 || uv tool install --force --editable "$SPEC"
  uv tool update-shell >/dev/null 2>&1 || true   # agrega ~/.local/bin al PATH
elif command -v pipx >/dev/null 2>&1; then
  pipx install --force --editable "$SPEC"
  pipx ensurepath >/dev/null 2>&1 || true
else
  echo "No se encontró uv ni pipx. Instalando uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  uv tool install --force --editable "$SPEC" --python 3.12
fi

echo
echo "✔ agentes instalado: $(command -v agentes || echo '~/.local/bin/agentes (agrega ~/.local/bin a tu PATH)')"
echo "  Uso:  cd tu-proyecto && agentes install && claude"
