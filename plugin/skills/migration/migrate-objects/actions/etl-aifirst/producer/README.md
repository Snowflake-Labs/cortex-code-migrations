# AI-first callable producer

This source-only .NET project adapts the existing SnowConvert engine assemblies to the AI-first
desktop migration driver. It does not contain or rebuild the engine.

## Build

```bash
./build.sh
```

The engine comes from NuGet: the same four packages `Snowflake.SnowConvertDesktop.Sql` references
(`Mobilize.Snow.CodeProcessor`, `.Content`, `Artinsoft.Common.CoreAST`,
`Mobilize.Common.Store.SqliteStorage`), at the version read from that project's
`Mobilize.Snow.CodeProcessor` reference. The migrations-snowconvert bump bot rewrites that line, so
the producer moves with every engine bump; an engine API change it does not follow fails the bump's
build. `-p:EnginePackageVersion=<v>` builds against another release.

Pass `Release` as the first argument for a release build. Output is always written under this
directory at `bin/<Config>/net10.0/aifirst-migrate.dll`.

Developer override: `AIFIRST_ENGINE_BIN=/path/to/engine/bin` (or `-p:EngineBin=...`) references a
local engine build output by path instead of the packages.

## Use

```bash
export AIFIRST_EMITTER="$PWD/bin/Debug/net10.0/aifirst-migrate.dll"
bash ../scripts/aifirst-migrate.sh <platform-table.json> <source-document> <output-root>
```

The producer records the source platform in assessment reports, emits SSIS instrumentation only for
SSIS inputs, and preserves platform-derived model/reference names.

## Stage the plugin runtime

Build and stage the complete runtime closure into the ignored sibling `../bin/` directory:

```bash
./build-plugin.sh
```

The build copies the packages' RID-native libraries (`libe_sqlite3`, `libscai_state`) flat beside
the emitter; the smoke fails without them.

`BIN_DIR=/alternate/package/path` redirects staging for packaging jobs, and `BUILD_DIR` keeps the
intermediate build out of `bin/<Config>/`. The staging script replaces the destination, copies the
complete flat build output (managed dependencies, JSON runtime data, runtime configuration, and the
RID-native libraries), writes `.version` (`AIFIRST_VERSION`, default `dev`), and runs
`smoke-packaged.sh`, which checks the native assets and runs `--target-probe` from the packaged
directory.

`aifirst-migrate.sh` resolves the emitter, without `AIFIRST_EMITTER`, in this order: `aifirst/`
beside the real `scai` (`SCAI_CLI`, else `scai` on `PATH`), the plugin's `../bin/`, then
`bin/Debug/net10.0/` here. Beside `scai` it runs the apphost on the runtime `scai` bundles
(`DOTNET_ROOT` set to the `scai` folder); everywhere else it runs `dotnet <dll>`.

## Ship it with scai

`Snowflake.SnowConvert.Cli.csproj` (`BundleAifirstEmitter`, after Publish) copies `../bin/` into
`<PublishDir>/aifirst/`. If `../bin/` is empty it runs `build-plugin.sh` first. Where there is no
bash (Windows) it skips with a message; pass `-p:RequireAifirstEmitter=true` for a customer package,
which then fails rather than ship `scai` without the emitter.
