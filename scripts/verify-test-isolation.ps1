param([string]$Project = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath $Project).Path

function Get-RuntimeManifest {
    $records = @()
    foreach ($relative in @('backend/data', 'data')) {
        $target = Join-Path $taskRoot $relative
        if (Test-Path -LiteralPath $target) {
            foreach ($file in Get-ChildItem -LiteralPath $target -File -Recurse -Force) {
                $records += [pscustomobject]@{
                    Path = $file.FullName.Substring($taskRoot.Length + 1).Replace('\', '/')
                    SHA256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
                }
            }
        }
    }
    return @($records | Sort-Object Path)
}

function Get-ManifestDigest($records) {
    $json = ConvertTo-Json -InputObject @($records) -Compress
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($json)))).Replace('-', '').ToLowerInvariant()
    } finally { $sha.Dispose() }
}

# Hash bytes only; never print player text, database rows or private dotenv.
$before = Get-RuntimeManifest
$beforeDigest = Get-ManifestDigest $before
Push-Location -LiteralPath $taskRoot
try {
    npm run test:offline
    $testExit = $LASTEXITCODE
} finally { Pop-Location }
$after = Get-RuntimeManifest
$afterDigest = Get-ManifestDigest $after
$unchanged = $beforeDigest -eq $afterDigest
[pscustomobject]@{
    FilesBefore = $before.Count
    FilesAfter = $after.Count
    SHA256Before = $beforeDigest
    SHA256After = $afterDigest
    RuntimeDataUnchanged = $unchanged
    TestExitCode = $testExit
} | ConvertTo-Json
if ($testExit -ne 0 -or -not $unchanged) { exit 1 }
