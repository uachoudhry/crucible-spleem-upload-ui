# kill_uploader.ps1
# Kill leftover crucible-upload processes (Prefect server, serve_flows workers,
# main.py) that Ctrl+C on Windows tends to orphan. Filters on the 'crucible-upload'
# command line, so it will NOT touch the microscope app (QSPLEEM_RUN.py) or Jupyter.
#
# Usage:  powershell -ExecutionPolicy Bypass -File kill_uploader.ps1
#   (or right-click > Run with PowerShell)

$procs = Get-CimInstance Win32_Process -Filter "name='python.exe' or name='prefect.exe'" |
    Where-Object { $_.CommandLine -match 'crucible-upload' }

if (-not $procs) {
    Write-Host "No crucible-upload processes running."
} else {
    foreach ($p in $procs) {
        Write-Host ("killing PID {0}" -f $p.ProcessId)
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Write-Host ("Killed {0} crucible-upload process(es)." -f $procs.Count)
}

# report whether the Prefect (4200) / Flask (5000) ports are now free
foreach ($port in 4200, 5000) {
    $listening = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    if ($listening) {
        Write-Host ("WARNING: port {0} still LISTENING (PID {1})" -f $port, ($listening.OwningProcess -join ','))
    } else {
        Write-Host ("port {0} free" -f $port)
    }
}
