#!/usr/bin/env bash
set -euo pipefail

# Resolve the package from this script's physical location.  This keeps an
# invocation through a symlink tied to the real package and makes an installed
# helper safely recognize itself as its own source.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
exec python3 "$SCRIPT_DIR/install.py" "$@"
