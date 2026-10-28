# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Functions only. The SessionStart hook dot-sources this file.
# The Microsoft Store execution alias (WindowsApps\python.exe) is not a Python.

function Test-WindowsStorePythonStub {
    param([string]$Path)
    return [bool]($Path -and ($Path -match '[\\/]WindowsApps[\\/]'))
}

function Resolve-RealPython {
    foreach ($name in @("py", "python", "python3")) {
        $cmds = @(Get-Command $name -All -ErrorAction SilentlyContinue)
        foreach ($cmd in $cmds) {
            if (-not (Test-WindowsStorePythonStub $cmd.Source)) { return $cmd }
        }
    }
    return $null
}

# Python used to bootstrap pipx. $null when the only interpreter is the Store stub.
# Prefix is @("-3") for the Windows py launcher and empty for python.exe.
function Get-UvBootstrapPython {
    $cmd = Resolve-RealPython
    if (-not $cmd) { return $null }
    $prefix = @()
    if ($cmd.Name -match '^(?i)py(\.exe)?$') { $prefix = @("-3") }
    return [pscustomobject]@{ Exe = $cmd.Source; Prefix = $prefix }
}
