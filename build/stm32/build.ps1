param([Parameter(Mandatory=$true)][string]$KeilUv4)
$ErrorActionPreference = "Stop"
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$project = Join-Path $taskRoot "src/stm32/gpio_pl_test/MDK-ARM/GPIO_PL_Test.uvprojx"
$artifact = Join-Path $taskRoot "src/stm32/gpio_pl_test/MDK-ARM/GPIO_PL_Test/GPIO_PL_Test.hex"
$log = Join-Path $PSScriptRoot ("keil_build_" + [guid]::NewGuid().ToString("N") + ".log")
if (!(Test-Path -LiteralPath $KeilUv4 -PathType Leaf)) { throw "Keil executable missing" }
if (Test-Path -LiteralPath $artifact) { Remove-Item -LiteralPath $artifact }
& $KeilUv4 -r $project -t "GPIO_PL_Test" -o $log
$code = $LASTEXITCODE
if ($code -notin @(0,1)) { throw "Keil failed: $code" }
if (!(Test-Path -LiteralPath $log)) { throw "Build log missing" }
$text = Get-Content -LiteralPath $log -Raw
$summaries = [regex]::Matches($text, '(\d+)\s+Error\(s\)')
if ($summaries.Count -eq 0) { throw "Compiler summary missing" }
foreach ($summary in $summaries) { if ([int]$summary.Groups[1].Value -ne 0) { throw "Compiler errors" } }
if (!(Test-Path -LiteralPath $artifact -PathType Leaf)) { throw "New HEX missing" }
Write-Output "Build completed: $artifact"
Get-FileHash -LiteralPath $artifact -Algorithm SHA256
