#!/usr/bin/env bash
# One-command install of the renv research cockpit as an on-demand local site.
#
#   ./install.sh                          # https://renv.local  (Safari + Chrome)
#   ./install.sh renv.local renv.test     # several names, one cert
#   ./install.sh --http my.test           # plain http, no mkcert
#
# What it does, in order:
#   1. Python venv + editable install of the reref package
#   2. builds the cockpit UI (if Node is present; skips if dist/ already built)
#   3. mkcert local CA (trusted once, keychain prompt) + a multi-SAN cert
#   4. /etc/hosts → loopback (IPv4 + IPv6) for each domain   [one sudo prompt]
#   5. a socket-activated launchd agent: starts on the first request, idle-exits
#
# Nothing runs in the background afterwards — launchd holds the socket at
# near-zero cost and boots the server only when you open the page.
set -euo pipefail
cd "$(dirname "$0")"

DOMAINS=(); HTTP_FLAG=""; PASSTHRU=()
for arg in "$@"; do
  case "$arg" in
    --http)      HTTP_FLAG="--http" ;;
    --no-hosts)  PASSTHRU+=("--no-hosts") ;;
    -*)          PASSTHRU+=("$arg") ;;
    *)           DOMAINS+=("$arg") ;;
  esac
done
[ ${#DOMAINS[@]} -eq 0 ] && DOMAINS=("renv.local")

echo "▸ reref cockpit installer"
echo "  domains: ${DOMAINS[*]}"

# 1. venv + package -----------------------------------------------------------
if [ ! -d .venv ]; then
  echo "▸ creating .venv"
  python3 -m venv .venv
fi
./.venv/bin/python -m pip install --quiet --upgrade pip
echo "▸ installing the reref package (editable)"
./.venv/bin/python -m pip install --quiet -e .

# 2. build the cockpit UI -----------------------------------------------------
if [ ! -f cockpit/dist/index.html ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "▸ building the cockpit UI"
    ( cd cockpit && npm install --silent && npm run build --silent )
  else
    echo "! cockpit/dist not built and npm not found — the API works, but install Node"
    echo "  and run 'cd cockpit && npm install && npm run build' for the full UI."
  fi
fi

# 3. mkcert prereq (https path) ----------------------------------------------
if [ -z "$HTTP_FLAG" ] && ! command -v mkcert >/dev/null 2>&1; then
  echo "! mkcert not found — needed for the https padlock."
  echo "    brew install mkcert nss   # nss = Firefox trust"
  echo "  then re-run, or pass --http for a plain-http install."
  exit 1
fi

# 4 + 5. hosts + cert + launchd, all inside the CLI installer -----------------
DOMAIN_ARGS=()
for d in "${DOMAINS[@]}"; do DOMAIN_ARGS+=(--domain "$d"); done
echo "▸ installing cert, /etc/hosts (sudo), and the launchd agent"
./.venv/bin/reref web install ${HTTP_FLAG} "${DOMAIN_ARGS[@]}" "${PASSTHRU[@]}"
