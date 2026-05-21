#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="$HOME/.local/bin"
TARGET="$INSTALL_DIR/nudge"

mkdir -p "$INSTALL_DIR"
ln -sfn "$ROOT/bin/nudge" "$TARGET"
chmod +x "$ROOT/bin/nudge"

cat <<MSG
Nudge CLI installed.

Global command:
  nudge --help
  nudge "明天下午3点开会"

Fixed path command:
  $ROOT/bin/nudge --help
  $ROOT/bin/nudge "明天下午3点开会"
MSG

case ":$PATH:" in
  *":$INSTALL_DIR:"*) ;;
  *)
    cat <<MSG

Note: $INSTALL_DIR is not in your PATH for this shell.
Add this to your shell profile if needed:
  export PATH="$INSTALL_DIR:\$PATH"
MSG
    ;;
esac
