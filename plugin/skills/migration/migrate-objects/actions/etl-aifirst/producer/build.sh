#!/usr/bin/env bash
# Build the producer to a fixed, in-repo path so a caller can point
# AIFIRST_EMITTER at something this repo just built, instead of a POC bin someone hand-rsynced
# from a one-off /tmp staging directory.
#
# The engine comes from the same NuGet packages, at the same version, as the SQL code processor
# (see CallableMigrator.csproj). AIFIRST_ENGINE_BIN, when set, is a developer override that names a
# local engine build output instead.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${1:-Debug}"

if [[ -n "${AIFIRST_ENGINE_BIN:-}" && ! -d "$AIFIRST_ENGINE_BIN" ]]; then
  echo "build.sh: AIFIRST_ENGINE_BIN does not exist: $AIFIRST_ENGINE_BIN" >&2
  exit 2
fi

dotnet build "$HERE/CallableMigrator.csproj" -c "$CONFIG"

OUT="$HERE/bin/$CONFIG/net10.0/aifirst-migrate.dll"
if [ ! -f "$OUT" ]; then
  echo "build.sh: expected $OUT after a successful build and did not find it" >&2
  exit 1
fi

echo ""
echo "built: $OUT"
echo "run:   export AIFIRST_EMITTER=\"$OUT\""
