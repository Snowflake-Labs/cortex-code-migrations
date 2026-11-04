#!/usr/bin/env bash
# Stage the AI-First emitter as a self-contained runtime directory (dll, apphost, engine assemblies,
# their data and RID-native libraries) that runs from wherever it is copied, with no
# AIFIRST_EMITTER or AIFIRST_ENGINE_BIN.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ACTION_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG="${CONFIG:-Release}"
# Callers such as release packaging and make temp can stage into a package
# assembly area instead of mutating the checkout.
BIN_DIR="${BIN_DIR:-$ACTION_DIR/bin}"
DEFAULT_BUILD_DIR="$SCRIPT_DIR/bin/$CONFIG/net10.0"
BUILD_DIR="${BUILD_DIR:-$DEFAULT_BUILD_DIR}"

# The engine is the SQL code processor's own NuGet packages (CallableMigrator.csproj).
# AIFIRST_ENGINE_BIN is an optional developer override, honoured by the build.
if [ -n "${AIFIRST_ENGINE_BIN:-}" ] && [ ! -d "${AIFIRST_ENGINE_BIN}" ]; then
  echo "build-plugin.sh: AIFIRST_ENGINE_BIN does not exist: $AIFIRST_ENGINE_BIN" >&2
  exit 2
fi

if [ "$BUILD_DIR" = "$DEFAULT_BUILD_DIR" ]; then
  "$SCRIPT_DIR/build.sh" "$CONFIG"
else
  rm -rf "$BUILD_DIR"
  dotnet build "$SCRIPT_DIR/CallableMigrator.csproj" -c "$CONFIG" -o "$BUILD_DIR"
fi

EMITTER="$BUILD_DIR/aifirst-migrate.dll"
RUNTIMECONFIG="$BUILD_DIR/aifirst-migrate.runtimeconfig.json"
if [ ! -f "$EMITTER" ] || [ ! -f "$RUNTIMECONFIG" ]; then
  echo "build-plugin.sh: producer output is incomplete under $BUILD_DIR" >&2
  exit 1
fi

# Replace the directory so a dependency removed from a new build cannot survive
# as a stale packaged file and make the smoke test pass accidentally.
rm -rf "$BIN_DIR"
mkdir -p "$BIN_DIR"
find "$BUILD_DIR" -maxdepth 1 -type f -exec cp -p {} "$BIN_DIR/" \;
echo "${AIFIRST_VERSION:-dev}" > "$BIN_DIR/.version"

BIN_DIR="$BIN_DIR" "$SCRIPT_DIR/smoke-packaged.sh"

echo ""
echo "Done."
echo "  Runtime: $BIN_DIR/aifirst-migrate.dll"
echo "  Version: $BIN_DIR/.version"
