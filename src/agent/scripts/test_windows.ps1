$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    $validationCommit = & git rev-parse --short HEAD
    Write-Host "VERIFY_COMMIT=$validationCommit"
    & py -3.13 -B -m unittest discover -s tests -v
    $testExitCode = $LASTEXITCODE
    Write-Host "VERIFY_COMMIT=$validationCommit TEST_EXIT=$testExitCode"
} finally {
    Pop-Location
}
exit $testExitCode
