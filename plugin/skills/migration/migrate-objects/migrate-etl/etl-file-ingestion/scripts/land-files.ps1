#Requires -Version 5.1
<#
.SYNOPSIS
Upload the flat files an ingestion manifest names into the Snowflake landing stage.

.DESCRIPTION
Runs on the Windows host that owns the original ETL source files. Reads
ingestion-manifest.json directly, so it needs no regeneration when a
re-conversion changes the manifest.

Every upload is uncompressed and overwrites in place, because the generated
COPY names an exact object and treats the prefix as a landing slot.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File land-files.ps1 `
  -Manifest .\ingestion-manifest.json -Connection prod -Database MIGRATED -DryRun
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Manifest,
    [Parameter(Mandatory = $true)][string]$Connection,
    [Parameter(Mandatory = $true)][string]$Database,
    [string]$Schema,
    [string[]]$SourceId = @(),
    # Rewrite a manifest location prefix onto this host, e.g. 'C:=D:\mirror'
    [string[]]$PathRoot = @(),
    [int]$Parallel = 8,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$SupportedSchemaVersions = @('1.0')

# The stage destination goes into the PUT as a single-quoted literal, so a folder such as
# '2024 Q1' lands as itself. Only a landing_stage path of these characters may pass: no
# quote or backslash can close the literal, so a manifest cannot append another statement.
$StageDestPattern = '^@public\.landing_stage/(?:[A-Za-z0-9_. -]+/)+$'

$script:Transfers = New-Object System.Collections.ArrayList
$script:Skipped = New-Object System.Collections.ArrayList
$script:Empty = New-Object System.Collections.ArrayList
$script:Warnings = New-Object System.Collections.ArrayList
$script:Errors = New-Object System.Collections.ArrayList

function Test-StageDestination([string]$StageDest) {
    return $StageDest -match $StageDestPattern
}

# StrictMode stops on a property the manifest leaves out; land-files.py reads every
# optional field with a default, and this reads them the same way.
function Get-Field($Object, [string]$Name, $Default = $null) {
    if ($null -eq $Object) { return $Default }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property -or $null -eq $property.Value) { return $Default }
    return $property.Value
}

function Add-Note($Collection, $SourceId, $Reason) {
    [void]$Collection.Add([pscustomobject]@{ SourceId = $SourceId; Reason = $Reason })
}

function Add-Transfer($SourceId, $Package, $LocalSpec, $StageDest, $FileNames) {
    [void]$script:Transfers.Add([pscustomobject]@{
            SourceId  = $SourceId
            Package   = $Package
            LocalSpec = $LocalSpec
            StageDest = $StageDest
            FileNames = $FileNames
        })
}

function Get-PathRootMap {
    $map = @()
    foreach ($entry in $PathRoot) {
        $index = $entry.IndexOf('=')
        if ($index -lt 1 -or $index -eq $entry.Length - 1) {
            throw "-PathRoot must look like 'ORIGINAL=LOCAL', got '$entry'"
        }
        $map += [pscustomobject]@{
            Original = $entry.Substring(0, $index).Replace('\', '/').TrimEnd('/').ToLowerInvariant()
            Local    = $entry.Substring($index + 1)
        }
    }
    return , $map
}

function Resolve-Location($Original, $RootMap) {
    $normalized = $Original.Replace('\', '/')
    $lowered = $normalized.ToLowerInvariant()
    foreach ($mapping in $RootMap) {
        if ($lowered -eq $mapping.Original -or $lowered.StartsWith($mapping.Original + '/')) {
            $relative = $normalized.Substring($mapping.Original.Length).Trim('/')
            $candidate = if ($relative) { Join-Path $mapping.Local $relative } else { $mapping.Local }
            if (Test-Path -LiteralPath $candidate) { return (Resolve-Path -LiteralPath $candidate).ProviderPath }
        }
    }
    $direct = [Environment]::ExpandEnvironmentVariables($Original)
    # ProviderPath, not Path: for a UNC root Path is Microsoft.PowerShell.Core\FileSystem::\\server\share,
    # which neither prefixes Get-ChildItem's DirectoryName nor belongs in a file:// URI.
    if (Test-Path -LiteralPath $direct) { return (Resolve-Path -LiteralPath $direct).ProviderPath }
    return $null
}

function Find-Root($Source, $RootMap) {
    foreach ($original in @(Get-Field $Source 'originalLocations' @())) {
        $resolved = Resolve-Location $original $RootMap
        if ($resolved) { return $resolved }
    }
    return $null
}

function Plan-Exact($Source, $SourceId, $Root, $StagePrefix) {
    $fileName = Get-Field $Source.selection 'fileName'
    if (-not $fileName) {
        Add-Note $script:Errors $SourceId 'exact selection has no fileName'
        return
    }
    $candidate = if (Test-Path -LiteralPath $Root -PathType Leaf) { $Root } else { Join-Path $Root $fileName }
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        Add-Note $script:Errors $SourceId "file does not exist: $candidate"
        return
    }
    Add-Transfer $SourceId (Get-Field $Source 'packageName' '') $candidate $StagePrefix @($fileName)
}

function Plan-Glob($Source, $SourceId, $Root, $StagePrefix) {
    $fileSpec = Get-Field $Source.selection 'fileSpec'
    if (-not $fileSpec) {
        Add-Note $script:Errors $SourceId 'glob selection has no fileSpec'
        return
    }
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        Add-Note $script:Errors $SourceId "directory does not exist: $Root"
        return
    }

    $recurse = (Get-Field $Source.selection 'recurse') -eq $true
    $found = Get-ChildItem -LiteralPath $Root -File -Recurse:$recurse |
        Where-Object { $_.Name -like $fileSpec }

    if (-not $found) {
        Add-Note $script:Empty $SourceId "no files match '$fileSpec' under $Root"
        return
    }

    $flatten = (Get-Field $Source 'destinationKeyPolicy' 'basename') -eq 'basename'
    $packageName = Get-Field $Source 'packageName' ''
    # A root given as C:\data\ (or a drive root) keeps its separator, while DirectoryName
    # never does for a subfolder, so measure from the trimmed root.
    $rootLength = $Root.TrimEnd('\', '/').Length

    # One PUT per directory rather than per file: the wildcard uploads the whole
    # directory in parallel, which is what makes hundreds of files practical.
    foreach ($group in $found | Group-Object DirectoryName | Sort-Object Name) {
        if ($flatten) {
            $stageDest = $StagePrefix
        }
        else {
            $relative = $group.Name.Substring([Math]::Min($rootLength, $group.Name.Length)).Replace('\', '/').Trim('/')
            $stageDest = if ($relative) { "$StagePrefix$relative/" } else { $StagePrefix }
        }
        if (-not (Test-StageDestination $stageDest)) {
            Add-Note $script:Errors $SourceId "stage path is not a landing_stage path: $stageDest"
            continue
        }
        Add-Transfer $SourceId $packageName (Join-Path $group.Name $fileSpec) $stageDest @($group.Group.Name)
    }
}

function Find-Collisions {
    # Two different files landing on one stage object means the second wins silently.
    # Within one source that is the declared consequence of 'basename' plus recurse
    # -- same-named files in sibling directories flatten onto one prefix -- so it is a
    # loud warning, not a failure. Across two sources it is a contradiction in the
    # plan: the error is recorded here, and the main block refuses to upload anything.
    $seen = @{}
    $flattened = @{}
    foreach ($transfer in $script:Transfers) {
        foreach ($name in $transfer.FileNames) {
            $key = $transfer.StageDest + $name
            $origin = "$($transfer.SourceId)|$($transfer.LocalSpec)"
            if (-not $seen.ContainsKey($key)) {
                $seen[$key] = $origin
            }
            elseif ($seen[$key] -eq $origin) {
                continue
            }
            elseif ($seen[$key].Split('|')[0] -eq $transfer.SourceId) {
                if (-not $flattened.ContainsKey($transfer.SourceId)) {
                    $flattened[$transfer.SourceId] = New-Object System.Collections.ArrayList
                }
                [void]$flattened[$transfer.SourceId].Add($name)
            }
            else {
                Add-Note $script:Errors $transfer.SourceId `
                    "$($seen[$key].Split('|')[0]) and $($transfer.SourceId) both land on $key"
            }
        }
    }

    foreach ($sourceId in $flattened.Keys) {
        $names = $flattened[$sourceId]
        $sample = (($names | Sort-Object -Unique | Select-Object -First 3) -join ', ')
        Add-Note $script:Warnings $sourceId ("$($names.Count) file name(s) repeat across recursed " +
            "subdirectories and flatten onto one prefix (e.g. $sample) -- only the last upload of each " +
            'survives. Change destinationKeyPolicy to relativeFromRoot if every file must land.')
    }
}

function Build-Plan($ManifestObject, $RootMap) {
    $version = Get-Field $ManifestObject 'schemaVersion'
    if ($SupportedSchemaVersions -notcontains $version) {
        throw ("Manifest schemaVersion '$version' is not supported by this " +
            "script (expected $($SupportedSchemaVersions -join ', ')). Get a newer script rather than " +
            'editing this one -- the field names may have changed.')
    }

    foreach ($source in @(Get-Field $ManifestObject 'sources' @())) {
        $id = Get-Field $source 'id' '<no id>'
        if ($SourceId.Count -gt 0 -and $SourceId -notcontains $id) { continue }

        if ((Get-Field $source 'resolutionState') -ne 'resolved') {
            Add-Note $script:Skipped $id 'conversion could not resolve a real path'
            continue
        }

        $stagePrefix = Get-Field (Get-Field $source 'mapping') 'expectedStagePrefix'
        if (-not $stagePrefix) {
            Add-Note $script:Skipped $id 'manifest has no mapping.expectedStagePrefix'
            continue
        }
        if (-not $stagePrefix.EndsWith('/')) { $stagePrefix += '/' }
        if (-not (Test-StageDestination $stagePrefix)) {
            Add-Note $script:Errors $id "stage prefix is not a landing_stage path: $stagePrefix"
            continue
        }

        $root = Find-Root $source $RootMap
        if (-not $root) {
            $locations = (@(Get-Field $source 'originalLocations' @()) -join ', ')
            if (-not $locations) { $locations = '<none>' }
            Add-Note $script:Errors $id "none of these exist on this host: $locations (try -PathRoot)"
            continue
        }

        $kind = Get-Field (Get-Field $source 'selection') 'kind'
        switch ($kind) {
            'exact' { Plan-Exact $source $id $root $stagePrefix }
            'glob' { Plan-Glob $source $id $root $stagePrefix }
            default { Add-Note $script:Errors $id "unsupported selection kind '$kind'" }
        }
    }

    Find-Collisions
}

function Invoke-Put($Transfer) {
    # Snowflake reads backslash escapes inside a quoted literal (\t in C:\data\temp is a tab),
    # so a Windows path goes into the file:// URI with forward slashes, which PUT accepts.
    $escaped = $Transfer.LocalSpec.Replace('\', '/').Replace("'", "''")
    $query = "PUT 'file://$escaped' '$($Transfer.StageDest)' " +
    "AUTO_COMPRESS = FALSE OVERWRITE = TRUE PARALLEL = $Parallel"

    $arguments = @('sql', '-q', $query, '-c', $Connection, '--database', $Database)
    if ($Schema) { $arguments += @('--schema', $Schema) }

    # Out-Host keeps snow's own output off the pipeline; a bare call would make this
    # function return that output alongside the exit code.
    & snow @arguments | Out-Host
    return $LASTEXITCODE
}

# --- main ---------------------------------------------------------------

if (-not (Test-Path -LiteralPath $Manifest -PathType Leaf)) {
    Write-Error "Manifest not found: $Manifest"
    exit 1
}

$manifestObject = Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
Build-Plan $manifestObject (Get-PathRootMap)

foreach ($note in $script:Skipped) { Write-Host "SKIPPED  $($note.SourceId): $($note.Reason)" }
foreach ($note in $script:Empty) { Write-Host "NO FILES $($note.SourceId): $($note.Reason)" }
foreach ($note in $script:Warnings) { Write-Host "WARN     $($note.SourceId): $($note.Reason)" -ForegroundColor Yellow }
foreach ($note in $script:Errors) { Write-Host "ERROR    $($note.SourceId): $($note.Reason)" -ForegroundColor Red }
foreach ($transfer in $script:Transfers) {
    Write-Host "UPLOAD   $($transfer.LocalSpec) -> $($transfer.StageDest) ($($transfer.FileNames.Count) file(s))"
}

$totalFiles = ($script:Transfers | ForEach-Object { $_.FileNames.Count } | Measure-Object -Sum).Sum
if (-not $totalFiles) { $totalFiles = 0 }
$sourceCount = ($script:Transfers | Select-Object -ExpandProperty SourceId -Unique | Measure-Object).Count

Write-Host ''
Write-Host ("$(if ($DryRun) { 'DRY RUN' } else { 'UPLOAD' }): $totalFiles file(s) from $sourceCount " +
    "source(s), $($script:Warnings.Count) warning(s), $($script:Errors.Count) error(s)")

if ($DryRun) {
    Write-Host 'Nothing uploaded. Re-run without -DryRun to transfer.'
    exit $(if ($script:Errors.Count) { 1 } else { 0 })
}

$collision = @($script:Errors | Where-Object { $_.Reason -like '*both land on*' })
if ($collision.Count -gt 0) {
    Write-Host ('Stopped before any PUT: two sources claim the same stage object. ' +
        'OVERWRITE = TRUE would let the last writer replace it.') -ForegroundColor Red
    exit 1
}

$failed = @{}
foreach ($transfer in $script:Transfers) {
    Write-Host "[$($transfer.SourceId)] $($transfer.FileNames.Count) file(s) -> $($transfer.StageDest)"
    $exitCode = Invoke-Put $transfer
    if ($exitCode -ne 0) {
        # Keep going: one unreachable package should not strand the other hundreds.
        $failed[$transfer.SourceId] = $true
        Write-Host "  FAILED (snow exited $exitCode)" -ForegroundColor Red
    }
}

Write-Host ''
Write-Host ("Done. $($sourceCount - $failed.Count) source(s) uploaded, $($failed.Count) failed, " +
    "$($script:Errors.Count) error(s).")
exit $(if ($failed.Count -or $script:Errors.Count) { 1 } else { 0 })
