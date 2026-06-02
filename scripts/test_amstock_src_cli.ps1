param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$OutDir = "",
    [switch]$SkipBroadQueries
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $OutDir) {
    $OutDir = Join-Path $ProjectRoot "tmp\amstock_src_cli_test"
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# Avoid uv warnings when another virtual environment is already active.
if (Test-Path Env:VIRTUAL_ENV) {
    Remove-Item Env:VIRTUAL_ENV
}

$summaryPath = Join-Path $OutDir "summary.json"
$jsonlPath = Join-Path $OutDir "results.jsonl"
Remove-Item -LiteralPath $summaryPath, $jsonlPath -ErrorAction SilentlyContinue

$cases = @(
    @{
        Name = "capabilities"
        Args = @("run", "amstock_src", "capabilities")
        ExpectOk = $true
    },
    @{
        Name = "price-history-akshare"
        Args = @(
            "run", "amstock_src", "price-history",
            "--symbol", "600519",
            "--start-date", "20250501",
            "--end-date", "20250511",
            "--adjust", "qfq",
            "--limit", "3",
            "--no-proxy",
            "--ipv4"
        )
        ExpectOk = $true
    },
    @{
        Name = "exchange-summary-sse"
        Args = @(
            "run", "amstock_src", "exchange-summary",
            "--exchange", "sse",
            "--limit", "5",
            "--no-proxy",
            "--ipv4"
        )
        ExpectOk = $true
    },
    @{
        Name = "exchange-summary-szse"
        Args = @(
            "run", "amstock_src", "exchange-summary",
            "--exchange", "szse",
            "--date", "20250509",
            "--limit", "5",
            "--no-proxy",
            "--ipv4"
        )
        ExpectOk = $true
    },
    @{
        Name = "financial-abstract"
        Args = @(
            "run", "amstock_src", "financial-abstract",
            "--symbol", "600519",
            "--limit", "3",
            "--no-proxy",
            "--ipv4"
        )
        ExpectOk = $true
    },
    @{
        Name = "financial-report-income"
        Args = @(
            "run", "amstock_src", "financial-report",
            "--symbol", "600519",
            "--report-type", "income",
            "--limit", "2",
            "--no-proxy",
            "--ipv4"
        )
        ExpectOk = $true
    },
    @{
        Name = "stock-basic-baostock"
        Args = @(
            "run", "amstock_src", "stock-basic",
            "--symbol", "600519",
            "--limit", "2",
            "--no-proxy",
            "--ipv4"
        )
        ExpectOk = $true
    },
    @{
        Name = "industry-list-baostock"
        Args = @(
            "run", "amstock_src", "industry-list",
            "--limit", "5",
            "--no-proxy",
            "--ipv4"
        )
        ExpectOk = $true
    }
)

if (-not $SkipBroadQueries) {
    $cases += @{
        Name = "a-spot-baostock"
        Args = @(
            "run", "amstock_src", "a-spot",
            "--date", "20260601",
            "--limit", "5",
            "--no-proxy",
            "--ipv4"
        )
        ExpectOk = $true
    }
}

function Get-FirstJsonObject {
    param([string[]]$Lines)

    foreach ($line in $Lines) {
        $trimmed = $line.Trim()
        if ($trimmed.StartsWith("{") -and $trimmed.EndsWith("}")) {
            return $trimmed | ConvertFrom-Json
        }
    }

    throw "No JSON object found in command output."
}

function Invoke-AmstockSrcCase {
    param([hashtable]$Case)

    $name = [string]$Case.Name
    $rawPath = Join-Path $OutDir "$name.raw.txt"

    Write-Host "==> $name"
    Push-Location $ProjectRoot
    try {
        $output = & uv @($Case.Args) 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }

    $output | Set-Content -LiteralPath $rawPath -Encoding UTF8

    $parsed = $null
    $parseError = $null
    try {
        $parsed = Get-FirstJsonObject -Lines $output
    } catch {
        $parseError = $_.Exception.Message
    }

    $ok = $false
    $source = $null
    $function = $null
    $returnedRows = $null
    $fallbackFrom = $null
    $errorType = $null
    $errorMessage = $null

    if ($null -ne $parsed) {
        if ($parsed.PSObject.Properties.Name -contains "ok") {
            $ok = [bool]$parsed.ok
        }
        if ($parsed.PSObject.Properties.Name -contains "source") {
            $source = $parsed.source
        }
        if ($parsed.PSObject.Properties.Name -contains "function") {
            $function = $parsed.function
        }
        if ($parsed.PSObject.Properties.Name -contains "returned_rows") {
            $returnedRows = $parsed.returned_rows
        }
        if ($parsed.PSObject.Properties.Name -contains "fallback_from") {
            $fallbackFrom = $parsed.fallback_from.function
        }
        if ($parsed.PSObject.Properties.Name -contains "error") {
            $errorType = $parsed.error.type
            $errorMessage = $parsed.error.message
        }
    }

    $passed = ($exitCode -eq 0) -and ($null -ne $parsed) -and ($ok -eq [bool]$Case.ExpectOk)

    $record = [ordered]@{
        name = $name
        passed = $passed
        exit_code = $exitCode
        ok = $ok
        source = $source
        function = $function
        returned_rows = $returnedRows
        fallback_from = $fallbackFrom
        error_type = $errorType
        error_message = $errorMessage
        parse_error = $parseError
        raw_output = $rawPath
        command = "uv " + (($Case.Args | ForEach-Object {
            if ($_ -match "\s") { '"' + $_ + '"' } else { $_ }
        }) -join " ")
    }

    ($record | ConvertTo-Json -Compress -Depth 8) | Add-Content -LiteralPath $jsonlPath -Encoding UTF8

    if ($passed) {
        $fallbackNote = if ($fallbackFrom) { " fallback=$fallbackFrom" } else { "" }
        Write-Host "PASS $name source=$source function=$function rows=$returnedRows$fallbackNote"
    } else {
        Write-Host "FAIL $name exit=$exitCode ok=$ok error=$errorType"
    }

    return [pscustomobject]$record
}

$results = foreach ($case in $cases) {
    Invoke-AmstockSrcCase -Case $case
}

$summary = [ordered]@{
    generated_at = (Get-Date).ToString("s")
    project_root = $ProjectRoot
    output_dir = $OutDir
    total = @($results).Count
    passed = @($results | Where-Object { $_.passed }).Count
    failed = @($results | Where-Object { -not $_.passed }).Count
    results = $results
}

$summary | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Host ""
Write-Host "Summary: $($summary.passed)/$($summary.total) passed"
Write-Host "Summary JSON: $summaryPath"
Write-Host "JSONL results: $jsonlPath"

if ($summary.failed -gt 0) {
    exit 1
}
