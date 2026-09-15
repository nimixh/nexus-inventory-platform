$ErrorActionPreference = "Stop"

$Command = if ($args.Count -gt 0) { $args[0] } else { "sync-all" }
$Root = "C:\nexus-inventory\marg-hook"
$LogDir = "C:\nexus-inventory\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Python = if ($env:NEXUS_MARG_PYTHON) {
    $env:NEXUS_MARG_PYTHON
} elseif (Test-Path ".\.venv\Scripts\python.exe") {
    ".\.venv\Scripts\python.exe"
} else {
    "python"
}

$Script = Join-Path $Root "nexus_marg_sync.py"
$LogFile = Join-Path $LogDir ("marg-sync-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")

try {
    $Output = & $Python $Script $Command 2>&1
    $ExitCode = $LASTEXITCODE
    $Output | Out-File -FilePath $LogFile -Encoding utf8

    Add-Type -AssemblyName System.Windows.Forms
    if ($ExitCode -eq 0) {
        [System.Windows.Forms.MessageBox]::Show(
            "Data synced with Nexus Inventory Platform successfully.",
            "Nexus Inventory Platform",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
        exit 0
    }

    [System.Windows.Forms.MessageBox]::Show(
        "Nexus Inventory Platform sync failed. Please check " + $LogFile,
        "Nexus Inventory Platform",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
    exit $ExitCode
} catch {
    $_ | Out-File -FilePath $LogFile -Encoding utf8
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        "Nexus Inventory Platform sync failed. Please check " + $LogFile,
        "Nexus Inventory Platform",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
    exit 1
}
