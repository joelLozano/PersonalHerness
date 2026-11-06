#!/usr/bin/env bash
# =============================================================================
#  requisitos.sh — verifica el software que necesita el harness `agentes` (y tu
#  proyecto) y ofrece instalar lo que falte, uno por uno.
#
#  Uso:
#    ./requisitos.sh                      # revisa e instala interactivamente (s/n)
#    ./requisitos.sh --proyecto ~/app     # incluye lo que pide ese proyecto (node, docker, go...)
#    ./requisitos.sh --check              # solo revisa (exit 1 si falta algo requerido)
#    ./requisitos.sh --yes                # instala todo lo faltante sin preguntar
#    ./requisitos.sh --solo-requeridos    # ignora recomendados/opcionales
#    ./requisitos.sh --lista              # muestra el catálogo completo
#
#  Requisitos extra por proyecto: .agentes/requisitos.conf (mismo formato que el
#  catálogo de abajo). Compatible con bash 3.2 (macOS).
# =============================================================================
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT="$PWD"
MODE="interactive"      # interactive | check | yes
ONLY_REQUIRED=0
SHOW_LIST=0

while [ $# -gt 0 ]; do
  case "$1" in
    --proyecto|-p|--path|-C) PROJECT="$(cd "${2:-.}" && pwd)"; shift ;;
    --check|-c) MODE="check" ;;
    --yes|-y|--todos) MODE="yes" ;;
    --solo-requeridos|-r) ONLY_REQUIRED=1 ;;
    --lista|-l) SHOW_LIST=1 ;;
    -h|--help) sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^#  \{0,1\}//'; exit 0 ;;
    *) echo "Opción desconocida: $1 (usa --help)"; exit 2 ;;
  esac
  shift
done

# ----------------------------------------------------------------------------- entorno
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; C=$'\033[36m'; D=$'\033[2m'; N=$'\033[0m'
else B=""; G=""; Y=""; R=""; C=""; D=""; N=""; fi

# rutas donde suelen quedar los instaladores (para detectar sin abrir otra terminal)
refresh_path() {
  local d
  for d in "$HOME/.local/bin" "$HOME/.cargo/bin" "$HOME/.bun/bin" /opt/homebrew/bin /usr/local/bin; do
    case ":$PATH:" in *":$d:"*) ;; *) [ -d "$d" ] && PATH="$d:$PATH" ;; esac
  done
  export PATH
  hash -r 2>/dev/null || true
}
refresh_path

OS="linux"; PKG=""
case "$(uname -s)" in
  Darwin) OS="mac" ;;
  Linux)
    SUDO=""; [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1 && SUDO="sudo "
    if command -v apt-get >/dev/null 2>&1; then PKG="${SUDO}apt-get install -y"
    elif command -v dnf >/dev/null 2>&1; then PKG="${SUDO}dnf install -y"
    elif command -v pacman >/dev/null 2>&1; then PKG="${SUDO}pacman -S --noconfirm"
    elif command -v zypper >/dev/null 2>&1; then PKG="${SUDO}zypper install -y"
    elif command -v apk >/dev/null 2>&1; then PKG="${SUDO}apk add"
    fi ;;
  *) echo "Sistema no soportado: $(uname -s) (usa macOS, Linux o WSL)"; exit 2 ;;
esac

# ----------------------------------------------------------------------------- catálogo
# id|nivel|version_min|comando_version|instalar_mac|instalar_linux|cuando|descripcion
#   nivel: requerido | recomendado | opcional
#   version_min: "-" = cualquier versión
#   instalar: brew:<formula> cask:<app> pkg:<paquete> npm:<paquete> fn:<funcion> cmd:<comando> | "-" = no aplica
#   cuando: siempre | mac | linux | archivos separados por coma que activan el requisito en el proyecto
catalog() {
cat <<'EOF'
xcode-clt|requerido|-|ver_xcode|fn:xcode|-|mac|Command Line Tools de Apple (git, make, compiladores)
brew|requerido|-|brew --version|fn:brew|-|mac|Homebrew, gestor de paquetes de macOS
git|requerido|2.30|git --version|brew:git|pkg:git|siempre|Control de versiones
curl|requerido|-|curl --version|brew:curl|pkg:curl|siempre|Descargas desde la terminal
uv|requerido|0.4|uv --version|fn:uv|fn:uv|siempre|Gestor de Python; instala y aísla el CLI agentes
claude|requerido|-|claude --version|fn:claude|fn:claude|siempre|Claude Code (orquestador del equipo)
agentes|requerido|0.1.0|agentes --version|fn:agentes|fn:agentes|siempre|CLI del harness de agentes
chromadb|recomendado|-|ver_chromadb|fn:chromadb|fn:chromadb|siempre|Base vectorial para la memoria semántica
fastembed|recomendado|-|ver_fastembed|fn:chromadb|fn:chromadb|siempre|Embeddings multilingües (español) para la memoria
python3|recomendado|3.10|python3 --version|brew:python@3.12|pkg:python3|siempre|Python del sistema (uv puede usar el suyo)
gh|opcional|-|gh --version|brew:gh|pkg:gh|siempre|GitHub CLI (PRs e issues desde los agentes)
node|requerido|18|node --version|brew:node|pkg:nodejs|package.json|Node.js (runtime de JavaScript)
npm|requerido|-|npm --version|brew:node|pkg:npm|package-lock.json|npm
pnpm|requerido|-|pnpm --version|npm:pnpm|npm:pnpm|pnpm-lock.yaml,pnpm-workspace.yaml|pnpm
yarn|requerido|-|yarn --version|npm:yarn|npm:yarn|yarn.lock|Yarn
bun|requerido|-|bun --version|brew:oven-sh/bun/bun|fn:bun|bun.lockb,bun.lock|Bun
docker|recomendado|-|docker --version|cask:docker|fn:docker|Dockerfile,docker-compose.yml,docker-compose.yaml,compose.yml,compose.yaml|Docker
go|requerido|1.21|go version|brew:go|pkg:golang|go.mod|Go
cargo|requerido|-|cargo --version|fn:rust|fn:rust|Cargo.toml|Rust (cargo + rustc)
poetry|requerido|-|poetry --version|fn:poetry|fn:poetry|poetry.lock|Poetry
java|requerido|17|java -version|brew:openjdk@21|pkg:default-jdk|pom.xml,build.gradle,build.gradle.kts|Java JDK
mvn|requerido|-|mvn --version|brew:maven|pkg:maven|pom.xml|Maven
bundle|requerido|-|bundle --version|brew:ruby|pkg:ruby-bundler|Gemfile|Ruby + Bundler
composer|requerido|-|composer --version|brew:composer|pkg:composer|composer.json|Composer (PHP)
make|requerido|-|make --version|fn:xcode|pkg:make|Makefile|GNU Make
EOF
  if [ -f "$PROJECT/.agentes/requisitos.conf" ]; then
    grep -v '^[[:space:]]*#' "$PROJECT/.agentes/requisitos.conf" | grep '|' || true
  fi
}

# ----------------------------------------------------------------------------- versiones especiales
ver_xcode() {
  xcode-select -p >/dev/null 2>&1 || return 1
  pkgutil --pkg-info=com.apple.pkg.CLTools_Executables 2>/dev/null | awk '/^version/{print $2}' || echo "instalado"
}
agentes_py() {
  local bin py
  bin="$(command -v agentes)" || return 1
  py="$(head -1 "$bin" | sed 's/^#![[:space:]]*//')"
  case "$py" in *python*) echo "$py" ;; *) echo python3 ;; esac
}
ver_fastembed() {
  local py; py="$(agentes_py)" || return 1
  "$py" -c 'import importlib.metadata as m; print(m.version("fastembed"))' 2>/dev/null
}
ver_chromadb() {
  local bin py
  bin="$(command -v agentes)" || return 1
  py="$(head -1 "$bin" | sed 's/^#![[:space:]]*//')"
  case "$py" in *python*) ;; *) py="python3" ;; esac
  "$py" -c 'import chromadb; print(chromadb.__version__)' 2>/dev/null
}

# ----------------------------------------------------------------------------- instaladores
inst_xcode()   { xcode-select --install; echo "${Y}Se abrió el instalador de Apple. Termínalo y vuelve a ejecutar este script.${N}"; }
inst_brew()    { /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" && load_brew; }
inst_uv()      { curl -LsSf https://astral.sh/uv/install.sh | sh; }
inst_claude()  { curl -fsSL https://claude.ai/install.sh | bash; }
inst_bun()     { curl -fsSL https://bun.sh/install | bash; }
inst_docker()  { curl -fsSL https://get.docker.com | ${SUDO:-}sh; }
inst_rust()    { curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y; }
inst_poetry()  { need uv && uv tool install poetry; }
inst_agentes() {
  if [ -x "$HARNESS_DIR/install.sh" ]; then "$HARNESS_DIR/install.sh"
  else echo "${R}No encuentro install.sh del harness en $HARNESS_DIR.${N} Clona el repositorio y ejecuta ./install.sh"; return 1; fi
}
inst_chromadb() {   # reinstala el CLI con la base vectorial
  if [ -x "$HARNESS_DIR/install.sh" ]; then "$HARNESS_DIR/install.sh"
  else need uv && uv tool install --force "agentes[vector]"; fi
}

load_brew() {
  command -v brew >/dev/null 2>&1 && return 0
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew /home/linuxbrew/.linuxbrew/bin/brew; do
    [ -x "$b" ] && eval "$("$b" shellenv)" && return 0
  done
  return 1
}
need() {
  case "$1" in
    brew) load_brew || { echo "${R}Necesitas Homebrew primero (instálalo cuando el script lo ofrezca).${N}"; return 1; } ;;
    *) command -v "$1" >/dev/null 2>&1 || { echo "${R}Necesitas '$1' primero.${N}"; return 1; } ;;
  esac
}

run_install() {   # $1 = especificación (brew:x, pkg:x, fn:x...)
  local spec="$1" kind="${1%%:*}" arg="${1#*:}"
  case "$kind" in
    brew) need brew && brew install $arg ;;
    cask) need brew && brew install --cask $arg ;;
    pkg)  [ -n "$PKG" ] || { echo "${R}No detecté gestor de paquetes (apt/dnf/pacman...).${N}"; return 1; }
          case "$PKG" in *apt-get*) ${SUDO:-}apt-get update -qq || true ;; esac
          $PKG $arg ;;
    npm)  need npm && npm install -g $arg ;;
    fn)   "inst_$arg" ;;
    cmd)  bash -c "$arg" ;;
    *)    echo "${R}Especificación de instalación inválida: $spec${N}"; return 1 ;;
  esac
}

# ----------------------------------------------------------------------------- comparación de versiones
ver_ge() {   # ver_ge actual minima  -> 0 si actual >= minima
  local IFS=. i x y
  local a=($1) b=($2)
  for ((i = 0; i < ${#b[@]}; i++)); do
    x="${a[i]:-0}"; y="${b[i]:-0}"
    x="${x%%[!0-9]*}"; y="${y%%[!0-9]*}"; x="${x:-0}"; y="${y:-0}"
    ((10#$x > 10#$y)) && return 0
    ((10#$x < 10#$y)) && return 1
  done
  return 0
}

# check_item <min> <comando_version>  -> define ST (ok|missing|old) y VER
check_item() {
  local min="$1" vcmd="$2" bin out
  bin="${vcmd%% *}"
  VER="-"; ST="missing"
  command -v "$bin" >/dev/null 2>&1 || return
  # en macOS sin Command Line Tools, /usr/bin/git|python3|make son "stubs" que abren un diálogo
  if [ "$OS" = mac ] && ! xcode-select -p >/dev/null 2>&1; then
    case "$(command -v "$bin")" in /usr/bin/git|/usr/bin/python3|/usr/bin/make) return ;; esac
  fi
  out="$(eval "$vcmd" </dev/null 2>&1)" || return
  VER="$(printf '%s' "$out" | grep -Eo '[0-9]+(\.[0-9]+)+' | head -1)"
  [ -z "$VER" ] && VER="$(printf '%s' "$out" | grep -Eo '[0-9]+' | head -1)"
  [ -z "$VER" ] && VER="instalado"
  if [ "$min" = "-" ] || [ "$VER" = "instalado" ] || ver_ge "$VER" "$min"; then ST="ok"; else ST="old"; fi
}

applies() {   # $1 = cuando
  case "$1" in
    siempre) return 0 ;;
    mac)   [ "$OS" = "mac" ] ;;
    linux) [ "$OS" = "linux" ] ;;
    *)
      local IFS=, f
      for f in $1; do
        [ -e "$PROJECT/$f" ] && return 0
        [ -n "$(find "$PROJECT" -maxdepth 3 -name "$f" -not -path '*/node_modules/*' -not -path '*/.git/*' 2>/dev/null | head -1)" ] && return 0
      done
      return 1 ;;
  esac
}

# ----------------------------------------------------------------------------- catálogo completo
if [ "$SHOW_LIST" = 1 ]; then
  printf "${B}%-11s %-12s %-9s %-28s %s${N}\n" SOFTWARE NIVEL MÍNIMA "SE PIDE CUANDO" DESCRIPCIÓN
  catalog | while IFS='|' read -r id lvl min vcmd im il when desc; do
    [ -z "$id" ] && continue
    printf "%-11s %-12s %-8s %-28s %s\n" "$id" "$lvl" "$min" "${when:0:28}" "$desc"
  done
  exit 0
fi

# ----------------------------------------------------------------------------- revisión
IDS=(); LVLS=(); MINS=(); VCMDS=(); INSTS=(); DESCS=(); STS=(); VERS=()
while IFS='|' read -r id lvl min vcmd im il when desc; do
  [ -z "$id" ] && continue
  [ "$ONLY_REQUIRED" = 1 ] && [ "$lvl" != "requerido" ] && continue
  applies "$when" || continue
  inst="$il"; [ "$OS" = "mac" ] && inst="$im"
  [ "$inst" = "-" ] && continue
  check_item "$min" "$vcmd"
  IDS+=("$id"); LVLS+=("$lvl"); MINS+=("$min"); VCMDS+=("$vcmd"); INSTS+=("$inst"); DESCS+=("$desc")
  STS+=("$ST"); VERS+=("$VER")
done < <(catalog)

if [ "$OS" = mac ]; then os_label="macOS $(sw_vers -productVersion 2>/dev/null) $(uname -m)"
else os_label="Linux $(uname -m)"; [ -n "$PKG" ] && os_label="$os_label · $(echo "${PKG#sudo }" | cut -d' ' -f1)"; fi
echo
echo "${B}requisitos.sh${N} — harness ${C}agentes${N}  ·  ${os_label}"
echo "${D}Proyecto analizado: $PROJECT${N}"
echo
echo "${B}Software requerido y versiones${N}"
printf "  ${B}%-3s %-11s %-13s %-12s %-12s %s${N}\n" "" SOFTWARE MÍNIMA INSTALADA NIVEL DESCRIPCIÓN
MISSING=(); REQ_MISSING=0
for ((i = 0; i < ${#IDS[@]}; i++)); do
  case "${STS[i]}" in
    ok)      icon="${G}✔${N}" ;;
    old)     icon="${Y}↑${N}" ;;
    missing) icon="${R}✘${N}" ;;
  esac
  min="${MINS[i]}"; [ "$min" = "-" ] && min="cualquiera" || min=">= $min"
  printf "  %s   %-11s %-12s %-12s %-12s %s\n" "$icon" "${IDS[i]}" "$min" "${VERS[i]}" "${LVLS[i]}" "${DESCS[i]}"
  if [ "${STS[i]}" != "ok" ]; then
    MISSING+=("$i")
    [ "${LVLS[i]}" = "requerido" ] && REQ_MISSING=$((REQ_MISSING + 1))
  fi
done
echo
echo "  ${D}✔ instalado   ↑ versión antigua   ✘ falta${N}"
echo

if [ ${#MISSING[@]} -eq 0 ]; then
  echo "${G}${B}Todo listo.${N} No falta ningún software."
  exit 0
fi

echo "${B}Software faltante o desactualizado (${#MISSING[@]})${N}"
for i in "${MISSING[@]}"; do
  [ "${STS[i]}" = "old" ] && what="actualizar ${VERS[i]} → ${MINS[i]}+" || what="instalar"
  printf "  - %-11s %-14s %-26s ${D}%s${N}\n" "${IDS[i]}" "(${LVLS[i]})" "$what" "${INSTS[i]}"
done
echo

if [ "$MODE" = "check" ]; then
  echo "Ejecuta ${C}./requisitos.sh${N} (o ${C}agentes requisitos${N}) en tu terminal para instalarlos."
  [ $REQ_MISSING -gt 0 ] && exit 1 || exit 0
fi
if [ "$MODE" = "interactive" ] && ! { [ -r /dev/tty ] && : </dev/tty; } 2>/dev/null; then
  echo "${Y}Sin terminal interactiva: ejecuta este script directamente en tu consola para instalar.${N}"
  [ $REQ_MISSING -gt 0 ] && exit 1 || exit 0
fi

# ----------------------------------------------------------------------------- instalación una por una
INSTALLED=(); SKIPPED=(); FAILED=()
for i in "${MISSING[@]}"; do
  id="${IDS[i]}"
  check_item "${MINS[i]}" "${VCMDS[i]}"     # puede haberse resuelto por una instalación previa
  if [ "$ST" = "ok" ]; then
    echo "${G}✔${N} ${id} ya quedó disponible (${VER})."; INSTALLED+=("$id"); continue
  fi
  if [ "$MODE" = "yes" ]; then
    ans="s"
  else
    echo "${B}${id}${N} — ${DESCS[i]} (${LVLS[i]})"
    echo "  ${D}Se ejecutará: ${INSTS[i]}${N}"
    while true; do
      printf "  ¿Deseas instalarlo?  s = sí  ·  n = no  ·  t = todos los que faltan  ·  q = salir : "
      read -r ans </dev/tty || ans="q"
      case "$ans" in s|S|si|sí|y|Y|n|N|no|t|T|q|Q) break ;; esac
      echo "  Responde s, n, t o q."
    done
  fi
  case "$ans" in
    q|Q) echo "Saliendo."; break ;;
    n|N|no) SKIPPED+=("$id"); echo; continue ;;
    t|T) MODE="yes" ;;
  esac
  echo "${C}→ Instalando ${id}…${N}"
  if run_install "${INSTS[i]}"; then
    refresh_path; load_brew >/dev/null 2>&1 || true
    check_item "${MINS[i]}" "${VCMDS[i]}"
    if [ "$ST" = "ok" ]; then echo "${G}✔ ${id} ${VER} instalado.${N}"; INSTALLED+=("$id")
    else echo "${Y}! ${id}: el instalador terminó, pero aún no se detecta (abre una terminal nueva y vuelve a revisar).${N}"; INSTALLED+=("$id*"); fi
  else
    echo "${R}✘ Falló la instalación de ${id}.${N}"; FAILED+=("$id")
  fi
  echo
done

echo "${B}Resumen${N}"
[ ${#INSTALLED[@]} -gt 0 ] && echo "  ${G}Instalados:${N} ${INSTALLED[*]}"
[ ${#SKIPPED[@]} -gt 0 ]   && echo "  ${Y}Omitidos:${N}   ${SKIPPED[*]}"
[ ${#FAILED[@]} -gt 0 ]    && echo "  ${R}Fallidos:${N}   ${FAILED[*]}"
echo "  ${D}Abre una terminal nueva para que el PATH se actualice. Vuelve a revisar con: ./requisitos.sh --check${N}"
[ ${#FAILED[@]} -gt 0 ] && exit 1
exit 0
