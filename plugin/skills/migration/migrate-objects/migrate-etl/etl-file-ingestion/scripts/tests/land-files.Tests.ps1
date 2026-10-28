#Requires -Version 5.1

$Uploader = if ($env:LAND_FILES_PS1) {
    $env:LAND_FILES_PS1
}
else {
    Join-Path (Split-Path $PSScriptRoot -Parent) 'land-files.ps1'
}

$PowerShellExe = if ($PSVersionTable.PSEdition -eq 'Core') {
    (Get-Process -Id $PID).Path
}
else {
    Join-Path $PSHOME 'powershell.exe'
}

function Invoke-Uploader([string[]]$Arguments) {
    $output = & $PowerShellExe -NoProfile -ExecutionPolicy Bypass -File $Uploader @Arguments 2>&1
    [pscustomobject]@{
        ExitCode = $LASTEXITCODE
        Output = ($output | Out-String)
    }
}

# Windows PowerShell 5.1 has no $IsWindows; it only ever runs on Windows.
$OnWindows = (-not (Test-Path variable:IsWindows)) -or $IsWindows

function ConvertTo-JsonText([string]$Text) {
    return $Text.Replace('\', '\\')
}

function Write-Manifest([string]$Path, [string]$SourcesJson) {
    Set-Content -Encoding ASCII $Path @"
{
  "schemaVersion": "1.0",
  "stage": { "name": "public.landing_stage" },
  "sources": [$SourcesJson]
}
"@
}

# A fake snow on PATH that appends its arguments to $Calls, one line per call.
function Install-FakeSnow([string]$Bin, [string]$Calls) {
    New-Item -ItemType Directory -Force $Bin | Out-Null
    if ($OnWindows) {
        Set-Content -Encoding ASCII (Join-Path $Bin 'snow.cmd') @"
@echo off
echo %*>>"$Calls"
exit /b 0
"@
    }
    else {
        $fake = Join-Path $Bin 'snow'
        Set-Content -Encoding ASCII $fake "#!/bin/sh`necho `"`$*`" >> '$Calls'`nexit 0"
        & chmod +x $fake
    }
    return "$Bin$([IO.Path]::PathSeparator)$env:PATH"
}

Describe 'land-files.ps1 integration' {
    BeforeEach {
        $script:Root = Join-Path ([IO.Path]::GetTempPath()) "land-files-$([Guid]::NewGuid())"
        $script:Data = Join-Path $script:Root 'data'
        New-Item -ItemType Directory -Force $script:Data | Out-Null
    }

    AfterEach {
        Remove-Item $script:Root -Recurse -Force -ErrorAction SilentlyContinue
    }

    It 'plans a one-source, one-location exact manifest' {
        Set-Content -Encoding ASCII (Join-Path $script:Data 'employees.csv') 'id,name'
        $manifest = @"
{
  "schemaVersion": "1.0",
  "stage": { "name": "public.landing_stage" },
  "sources": [{
    "id": "single-source",
    "packageName": "Demo",
    "originalLocations": ["$($script:Data.Replace('\', '\\'))"],
    "selection": { "kind": "exact", "fileName": "employees.csv", "recurse": false },
    "resolutionState": "resolved",
    "mapping": { "expectedStagePrefix": "@public.landing_stage/demo" }
  }]
}
"@
        $manifestPath = Join-Path $script:Root 'manifest.json'
        Set-Content -Encoding ASCII $manifestPath $manifest

        $result = Invoke-Uploader @(
            '-Manifest', $manifestPath,
            '-Connection', 'test',
            '-Database', 'demo',
            '-DryRun'
        )

        $result.ExitCode | Should Be 0
        $result.Output | Should Match 'UPLOAD\s+.*employees\.csv -> @public\.landing_stage/demo/ \(1 file\(s\)\)'
        $result.Output | Should Match 'DRY RUN: 1 file\(s\) from 1 source\(s\), 0 warning\(s\), 0 error\(s\)'
    }

    It 'uses PathRoot and the manifest glob without descending' {
        Set-Content -Encoding ASCII (Join-Path $script:Data 'one.csv') '1,A'
        Set-Content -Encoding ASCII (Join-Path $script:Data 'ignore.txt') 'ignored'
        $nested = Join-Path $script:Data 'nested'
        New-Item -ItemType Directory $nested | Out-Null
        Set-Content -Encoding ASCII (Join-Path $nested 'nested.csv') '2,B'
        $manifest = @'
{
  "schemaVersion": "1.0",
  "stage": { "name": "public.landing_stage" },
  "sources": [{
    "id": "glob-source",
    "packageName": "Demo",
    "originalLocations": ["C:\\legacy\\drop"],
    "selection": { "kind": "glob", "fileSpec": "*.csv", "recurse": false },
    "destinationKeyPolicy": "basename",
    "resolutionState": "resolved",
    "mapping": { "expectedStagePrefix": "@public.landing_stage/glob/" }
  }]
}
'@
        $manifestPath = Join-Path $script:Root 'manifest.json'
        Set-Content -Encoding ASCII $manifestPath $manifest

        $result = Invoke-Uploader @(
            '-Manifest', $manifestPath,
            '-Connection', 'test',
            '-Database', 'demo',
            '-PathRoot', "C:\legacy\drop=$script:Data",
            '-DryRun'
        )

        $result.ExitCode | Should Be 0
        $result.Output | Should Match '@public\.landing_stage/glob/ \(1 file\(s\)\)'
        $result.Output | Should Not Match 'ignore\.txt'
        $result.Output | Should Not Match 'nested\.csv'
    }

    It 'executes snow with the exact safe PUT contract' {
        Set-Content -Encoding ASCII (Join-Path $script:Data 'employees.csv') 'id,name'
        $manifestPath = Join-Path $script:Root 'manifest.json'
        $location = $script:Data.Replace('\', '\\')
        Set-Content -Encoding ASCII $manifestPath @"
{
  "schemaVersion": "1.0",
  "stage": { "name": "public.landing_stage" },
  "sources": [{
    "id": "put-source",
    "packageName": "Demo",
    "originalLocations": ["$location"],
    "selection": { "kind": "exact", "fileName": "employees.csv", "recurse": false },
    "resolutionState": "resolved",
    "mapping": { "expectedStagePrefix": "@public.landing_stage/demo/" }
  }]
}
"@
        $calls = Join-Path $script:Root 'snow-args.txt'
        $oldPath = $env:PATH
        $env:PATH = Install-FakeSnow (Join-Path $script:Root 'bin') $calls
        try {
            $result = Invoke-Uploader @(
                '-Manifest', $manifestPath,
                '-Connection', 'test-connection',
                '-Database', 'demo-db',
                '-Schema', 'demo-schema',
                '-Parallel', '4'
            )
        }
        finally {
            $env:PATH = $oldPath
        }

        $result.ExitCode | Should Be 0
        $call = Get-Content -Raw $calls
        $call | Should Match "PUT 'file://.*employees\.csv' '@public\.landing_stage/demo/'"
        if ($OnWindows) {
            # A Windows path lands as file://C:/..., never with backslashes inside the quoted literal.
            $call | Should Match "PUT 'file://[A-Za-z]:/[^'\\]*employees\.csv'"
        }
        $call | Should Match 'AUTO_COMPRESS = FALSE'
        $call | Should Match 'OVERWRITE = TRUE'
        $call | Should Match 'PARALLEL = 4'
        $call | Should Match '-c test-connection --database demo-db --schema demo-schema'
    }

    It 'does not call snow when two sources claim one stage object' {
        Set-Content -Encoding ASCII (Join-Path $script:Data 'shared.csv') 'id,name'
        $other = Join-Path $script:Root 'other'
        New-Item -ItemType Directory $other | Out-Null
        Set-Content -Encoding ASCII (Join-Path $other 'shared.csv') 'id,name'
        $first = $script:Data.Replace('\', '\\')
        $second = $other.Replace('\', '\\')
        $manifestPath = Join-Path $script:Root 'manifest.json'
        Set-Content -Encoding ASCII $manifestPath @"
{
  "schemaVersion": "1.0",
  "stage": { "name": "public.landing_stage" },
  "sources": [
    {
      "id": "s1",
      "packageName": "Demo",
      "originalLocations": ["$first\\shared.csv"],
      "selection": { "kind": "exact", "fileName": "shared.csv", "recurse": false },
      "resolutionState": "resolved",
      "mapping": { "expectedStagePrefix": "@public.landing_stage/same/" }
    },
    {
      "id": "s2",
      "packageName": "Demo",
      "originalLocations": ["$second\\shared.csv"],
      "selection": { "kind": "exact", "fileName": "shared.csv", "recurse": false },
      "resolutionState": "resolved",
      "mapping": { "expectedStagePrefix": "@public.landing_stage/same/" }
    }
  ]
}
"@
        $calls = Join-Path $script:Root 'snow-args.txt'
        $oldPath = $env:PATH
        $env:PATH = Install-FakeSnow (Join-Path $script:Root 'bin') $calls
        try {
            $result = Invoke-Uploader @(
                '-Manifest', $manifestPath,
                '-Connection', 'test',
                '-Database', 'demo'
            )
        }
        finally {
            $env:PATH = $oldPath
        }

        $result.ExitCode | Should Be 1
        $result.Output | Should Match 'Stopped before any PUT'
        $result.Output | Should Match 'both land on'
        Test-Path $calls | Should Be $false
    }

    It 'treats recurse, packageName and resolutionState as optional, as land-files.py does' {
        Set-Content -Encoding ASCII (Join-Path $script:Data 'one.csv') '1,A'
        $location = ConvertTo-JsonText $script:Data
        $manifestPath = Join-Path $script:Root 'manifest.json'
        Write-Manifest $manifestPath @"
{
  "id": "bare-glob",
  "originalLocations": ["$location"],
  "selection": { "kind": "glob", "fileSpec": "*.csv" },
  "resolutionState": "resolved",
  "mapping": { "expectedStagePrefix": "@public.landing_stage/bare/" }
},
{
  "id": "no-state",
  "originalLocations": ["$location"],
  "selection": { "kind": "exact", "fileName": "one.csv" },
  "mapping": { "expectedStagePrefix": "@public.landing_stage/nostate/" }
},
{
  "id": "no-prefix",
  "resolutionState": "resolved",
  "mapping": {}
}
"@

        $result = Invoke-Uploader @('-Manifest', $manifestPath, '-Connection', 'test', '-Database', 'demo', '-DryRun')

        $result.ExitCode | Should Be 0
        $result.Output | Should Match 'UPLOAD\s+.*data[\\/]\*\.csv -> @public\.landing_stage/bare/ \(1 file\(s\)\)'
        $result.Output | Should Match 'SKIPPED\s+no-state: conversion could not resolve a real path'
        $result.Output | Should Match 'SKIPPED\s+no-prefix: manifest has no mapping\.expectedStagePrefix'
    }

    It 'keeps relativeFromRoot paths right when the root ends with a separator' {
        Set-Content -Encoding ASCII (Join-Path $script:Data 'top.csv') '1,A'
        $nested = Join-Path $script:Data 'nested'
        New-Item -ItemType Directory $nested | Out-Null
        Set-Content -Encoding ASCII (Join-Path $nested 'deep.csv') '2,B'
        $location = ConvertTo-JsonText ($script:Data + [IO.Path]::DirectorySeparatorChar)
        $manifestPath = Join-Path $script:Root 'manifest.json'
        Write-Manifest $manifestPath @"
{
  "id": "trailing",
  "originalLocations": ["$location"],
  "selection": { "kind": "glob", "fileSpec": "*.csv", "recurse": true },
  "destinationKeyPolicy": "relativeFromRoot",
  "resolutionState": "resolved",
  "mapping": { "expectedStagePrefix": "@public.landing_stage/rel/" }
}
"@

        $result = Invoke-Uploader @('-Manifest', $manifestPath, '-Connection', 'test', '-Database', 'demo', '-DryRun')

        $result.ExitCode | Should Be 0
        $result.Output | Should Match 'data[\\/]\*\.csv -> @public\.landing_stage/rel/ \(1 file\(s\)\)'
        $result.Output | Should Match 'nested[\\/]\*\.csv -> @public\.landing_stage/rel/nested/ \(1 file\(s\)\)'
    }

    It 'plans the provider path, not the provider-qualified one Resolve-Path gives UNC roots' {
        # Resolve-Path returns Microsoft.PowerShell.Core\FileSystem::\\server\share for a UNC
        # root; a provider-qualified location reproduces that on any host.
        Set-Content -Encoding ASCII (Join-Path $script:Data 'top.csv') '1,A'
        $nested = Join-Path $script:Data 'nested'
        New-Item -ItemType Directory $nested | Out-Null
        Set-Content -Encoding ASCII (Join-Path $nested 'deep.csv') '2,B'
        $location = ConvertTo-JsonText "Microsoft.PowerShell.Core\FileSystem::$($script:Data)"
        $manifestPath = Join-Path $script:Root 'manifest.json'
        Write-Manifest $manifestPath @"
{
  "id": "unc",
  "originalLocations": ["$location"],
  "selection": { "kind": "glob", "fileSpec": "*.csv", "recurse": true },
  "destinationKeyPolicy": "relativeFromRoot",
  "resolutionState": "resolved",
  "mapping": { "expectedStagePrefix": "@public.landing_stage/unc/" }
}
"@

        $result = Invoke-Uploader @('-Manifest', $manifestPath, '-Connection', 'test', '-Database', 'demo', '-DryRun')

        $result.ExitCode | Should Be 0
        $result.Output | Should Not Match 'FileSystem::'
        $result.Output | Should Match 'data[\\/]\*\.csv -> @public\.landing_stage/unc/ \(1 file\(s\)\)'
        $result.Output | Should Match 'nested[\\/]\*\.csv -> @public\.landing_stage/unc/nested/ \(1 file\(s\)\)'
    }

    It 'lands a subfolder with spaces under a quoted stage destination' {
        $spaced = Join-Path $script:Data '2024 Q1'
        New-Item -ItemType Directory $spaced | Out-Null
        Set-Content -Encoding ASCII (Join-Path $spaced 'sales.csv') '1,A'
        $location = ConvertTo-JsonText $script:Data
        $manifestPath = Join-Path $script:Root 'manifest.json'
        Write-Manifest $manifestPath @"
{
  "id": "spaced",
  "originalLocations": ["$location"],
  "selection": { "kind": "glob", "fileSpec": "*.csv", "recurse": true },
  "destinationKeyPolicy": "relativeFromRoot",
  "resolutionState": "resolved",
  "mapping": { "expectedStagePrefix": "@public.landing_stage/sales/" }
}
"@
        $calls = Join-Path $script:Root 'snow-args.txt'
        $oldPath = $env:PATH
        $env:PATH = Install-FakeSnow (Join-Path $script:Root 'bin') $calls
        try {
            $result = Invoke-Uploader @('-Manifest', $manifestPath, '-Connection', 'test', '-Database', 'demo')
        }
        finally {
            $env:PATH = $oldPath
        }

        $result.ExitCode | Should Be 0
        Get-Content -Raw $calls | Should Match "PUT 'file://.*2024 Q1/\*\.csv' '@public\.landing_stage/sales/2024 Q1/' AUTO_COMPRESS"
    }

    It 'accepts a stage prefix with a space but refuses one that would close the quoted literal' {
        Set-Content -Encoding ASCII (Join-Path $script:Data 'one.csv') '1,A'
        $location = ConvertTo-JsonText $script:Data
        $manifestPath = Join-Path $script:Root 'manifest.json'
        Write-Manifest $manifestPath @"
{
  "id": "spaced",
  "originalLocations": ["$location"],
  "selection": { "kind": "exact", "fileName": "one.csv" },
  "resolutionState": "resolved",
  "mapping": { "expectedStagePrefix": "@public.landing_stage/2024 Q1/" }
},
{
  "id": "quoted",
  "originalLocations": ["$location"],
  "selection": { "kind": "exact", "fileName": "one.csv" },
  "resolutionState": "resolved",
  "mapping": { "expectedStagePrefix": "@public.landing_stage/x' AUTO_COMPRESS = TRUE '/" }
}
"@

        $result = Invoke-Uploader @('-Manifest', $manifestPath, '-Connection', 'test', '-Database', 'demo', '-DryRun')

        $result.ExitCode | Should Be 1
        $result.Output | Should Match 'UPLOAD   .*one\.csv -> @public\.landing_stage/2024 Q1/ \(1 file\(s\)\)'
        $result.Output | Should Match 'ERROR    quoted: stage prefix is not a landing_stage path'
        $result.Output | Should Not Match 'ERROR    spaced'
    }
}
