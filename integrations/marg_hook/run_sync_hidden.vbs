Set shell = CreateObject("WScript.Shell")
cmd = "powershell.exe -WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File C:\nexus-inventory\marg-hook\nexus_marg_sync.ps1 sync-all"
shell.Run cmd, 0, False
