$ErrorActionPreference = "Stop"

$Target = "C:\nexus-inventory\marg-hook"
New-Item -ItemType Directory -Force -Path $Target | Out-Null
Copy-Item -LiteralPath `
    "$PSScriptRoot\nexus_marg_sync.py", `
    "$PSScriptRoot\nexus_marg_sync.ps1", `
    "$PSScriptRoot\run_sync_hidden.vbs", `
    "$PSScriptRoot\marg_footer_end_hook.txt", `
    "$PSScriptRoot\marg_full_sync_commands.txt" `
    -Destination $Target -Force

Write-Host "Installed Nexus Inventory Platform Marg hook sync kit to $Target"
