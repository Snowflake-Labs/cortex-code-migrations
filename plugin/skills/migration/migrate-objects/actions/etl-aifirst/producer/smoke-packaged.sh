#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ACTION_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BIN_DIR="${BIN_DIR:-$ACTION_DIR/bin}"
EMITTER="$BIN_DIR/aifirst-migrate.dll"

if [ ! -f "$EMITTER" ]; then
  echo "smoke-packaged.sh: packaged emitter is missing: $EMITTER" >&2
  exit 1
fi
if [ ! -f "$BIN_DIR/aifirst-migrate.runtimeconfig.json" ]; then
  echo "smoke-packaged.sh: packaged runtime configuration is missing" >&2
  exit 1
fi

# --target-probe drives TargetTranslator only; it never touches
# Microsoft.Data.Sqlite/ObjectReferenceCalculator or ScaiState, so a missing native
# asset would otherwise go undetected here and surface later as a TypeInitializationException.
case "$(uname -s 2>/dev/null || echo unknown)" in
  Darwin) NATIVE_PREFIX="lib"; NATIVE_EXT="dylib" ;;
  MINGW*|MSYS*|CYGWIN*) NATIVE_PREFIX=""; NATIVE_EXT="dll" ;;
  *) NATIVE_PREFIX="lib"; NATIVE_EXT="so" ;;
esac
NATIVES=("${NATIVE_PREFIX}e_sqlite3.$NATIVE_EXT")
if [ -f "$BIN_DIR/ScaiState.dll" ]; then
  NATIVES+=("${NATIVE_PREFIX}scai_state.$NATIVE_EXT")
fi
for native in "${NATIVES[@]}"; do
  if [ ! -f "$BIN_DIR/$native" ]; then
    echo "smoke-packaged.sh: packaged native asset is missing: $BIN_DIR/$native" >&2
    exit 1
  fi
done

# --target-probe executes real translator code, so the host must resolve the engine closure from
# BIN_DIR. In scai's aifirst/ folder it runs on the runtime bundled beside scai; a source checkout
# has none and uses the dotnet on PATH.
RUNTIME_ROOT="$(cd "$BIN_DIR/.." && pwd)"
case "$(uname -s 2>/dev/null || echo unknown)" in
  MINGW*|MSYS*|CYGWIN*) EMITTER_HOST="$BIN_DIR/aifirst-migrate.exe" ;;
  *) EMITTER_HOST="$BIN_DIR/aifirst-migrate" ;;
esac
if [ -d "$RUNTIME_ROOT/host/fxr" ] && [ -f "$EMITTER_HOST" ]; then
  export DOTNET_ROOT="$RUNTIME_ROOT"
  case "$(uname -m 2>/dev/null || echo unknown)" in
    x86_64|amd64) export DOTNET_ROOT_X64="$RUNTIME_ROOT" ;;
    aarch64|arm64) export DOTNET_ROOT_ARM64="$RUNTIME_ROOT" ;;
  esac
  "$EMITTER_HOST" --target-probe >/dev/null
  echo "packaged AI-First runtime smoke passed: $EMITTER_HOST --target-probe (runtime $RUNTIME_ROOT)"
elif command -v dotnet >/dev/null 2>&1; then
  dotnet "$EMITTER" --target-probe >/dev/null
  echo "packaged AI-First runtime smoke passed: dotnet $EMITTER --target-probe"
elif [ -f "$EMITTER_HOST" ]; then
  "$EMITTER_HOST" --target-probe >/dev/null
  echo "packaged AI-First runtime smoke passed: $EMITTER_HOST --target-probe"
else
  echo "smoke-packaged.sh: no bundled runtime beside $BIN_DIR, dotnet is not on PATH, and the apphost is missing" >&2
  exit 1
fi
