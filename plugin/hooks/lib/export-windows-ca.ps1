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

# Export the Windows trust store as a PEM CA bundle for tools that do not read
# it (Python requests/certifi, pip, Node, git's OpenSSL backend, conda, AWS CLI,
# WSL / Git Bash / MSYS2 / Cygwin OpenSSL), including company TLS-inspection CAs.
#
# Includes machine and user roots and intermediate CAs (the logical stores
# already merge Group Policy and enterprise certificates). Excludes expired and
# non-CA certificates and the Disallowed store.
#
# Usage:
#   powershell -NoProfile -File export-windows-ca.ps1 -OutFile "$env:USERPROFILE\windows-ca.pem"
#   powershell -NoProfile -File export-windows-ca.ps1 > windows-ca.pem   # stdout
# Then use it via NODE_EXTRA_CA_CERTS (adds to Node's list), or REQUESTS_CA_BUNDLE,
# PIP_CERT, SSL_CERT_FILE, AWS_CA_BUNDLE, `git config http.sslCAInfo` (these
# replace the tool's list).
#
# Windows downloads public roots on demand, so this export may lack rarely used
# ones. For settings that replace a tool's list, combine the tool's default
# bundle with this one (as trust-windows-ca.sh does).

param([string]$OutFile)

$ErrorActionPreference = 'Stop'

function Get-StoreCertificates {
    param([string]$Name)
    foreach ($location in 'LocalMachine', 'CurrentUser') {
        $store = [System.Security.Cryptography.X509Certificates.X509Store]::new($Name, $location)
        try { $store.Open('ReadOnly, OpenExistingOnly') } catch { continue }
        try {
            foreach ($cert in $store.Certificates) {
                [pscustomobject]@{ Cert = $cert; Store = "$location\$Name" }
            }
        } finally {
            $store.Close()
        }
    }
}

$disallowed = @{}
foreach ($entry in Get-StoreCertificates 'Disallowed') { $disallowed[$entry.Cert.Thumbprint] = $true }

# A CA per its Basic Constraints; an old v1 root without them only if self-signed.
function Test-CaCertificate {
    param($Cert)
    foreach ($ext in $Cert.Extensions) {
        if ($ext -is [System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension]) {
            return $ext.CertificateAuthority
        }
    }
    return $Cert.Subject -eq $Cert.Issuer
}

$now = Get-Date
$seen = @{}
$pem = [System.Text.StringBuilder]::new()
foreach ($entry in @(Get-StoreCertificates 'Root') + @(Get-StoreCertificates 'CA')) {
    $cert = $entry.Cert
    if ($seen.ContainsKey($cert.Thumbprint) -or $disallowed.ContainsKey($cert.Thumbprint)) { continue }
    if ($cert.NotAfter -lt $now -or -not (Test-CaCertificate $cert)) { continue }
    $seen[$cert.Thumbprint] = $true
    $base64 = [Convert]::ToBase64String($cert.RawData) -replace '(.{64})', "`$1`n"
    [void]$pem.Append("# $($cert.Subject)`n# $($entry.Store)  SHA1 $($cert.Thumbprint)`n")
    [void]$pem.Append("-----BEGIN CERTIFICATE-----`n$($base64.TrimEnd("`n"))`n-----END CERTIFICATE-----`n`n")
}

if ($OutFile) {
    $full = [System.IO.Path]::GetFullPath($OutFile)
    [System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($full)) | Out-Null
    # No BOM, LF endings: readable by OpenSSL, Python, Node, Java, and Go.
    [System.IO.File]::WriteAllText($full, $pem.ToString(), [System.Text.UTF8Encoding]::new($false))
    Write-Host "Wrote $($seen.Count) certificates to $full"
} else {
    $pem.ToString()
}
