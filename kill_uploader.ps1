# kill_uploader.ps1
# Kill leftover crucible-upload processes (Prefect server, serve_flows workers,
# main.py) that Ctrl+C on Windows tends to orphan.
#
# Two independent ways of finding them, because either one alone can miss:
#   1. Whoever is LISTENING on the Prefect (4200) / Flask (5000) ports. This
#      works even when the process cannot be introspected.
#   2. python.exe / prefect.exe whose CommandLine mentions crucible-upload.
# Win32_Process.CommandLine (and ExecutablePath) come back $null for processes
# started in a context this shell cannot query -- which is exactly the uploader
# in practice -- so a CommandLine-only filter silently finds nothing and reports
# success. The port lookup is what actually catches those.
#
# Never touches the microscope app (QSPLEEM_RUN.py) or Jupyter: port matches are
# limited to 4200/5000, and name matches require a crucible-upload command line.
#
# Usage:  powershell -ExecutionPolicy Bypass -File kill_uploader.ps1

$targets = @{}   # pid -> reason

foreach ($port in 4200, 5000) {
    Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
        ForEach-Object {
            $procId = $_.OwningProcess
            if ($procId -and $procId -ne 0) { $targets[[int]$procId] = "listening on $port" }
        }
}

Get-CimInstance Win32_Process -Filter "name='python.exe' or name='prefect.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'crucible-upload' } |
    ForEach-Object { $targets[[int]$_.ProcessId] = 'crucible-upload command line' }

# Also take the children of anything already condemned (serve_flows spawns workers).
foreach ($procId in @($targets.Keys)) {
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$procId" -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^(python|prefect)' } |
        ForEach-Object { if (-not $targets.ContainsKey([int]$_.ProcessId)) { $targets[[int]$_.ProcessId] = "child of $procId" } }
}

# Never kill the microscope app, whatever else matched.
foreach ($procId in @($targets.Keys)) {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
    if ($p -and $p.CommandLine -and $p.CommandLine -match 'QSPLEEM_RUN') {
        Write-Host ("SKIPPING pid {0} - that is the microscope app" -f $procId)
        $targets.Remove([int]$procId)
    }
}

if ($targets.Count -eq 0) {
    Write-Host "No crucible-upload processes running."
} else {
    foreach ($procId in $targets.Keys) {
        Write-Host ("killing PID {0} ({1})" -f $procId, $targets[$procId])
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
    Write-Host ("Killed {0} crucible-upload process(es)." -f $targets.Count)
}

Start-Sleep -Milliseconds 800

# Report whether the ports actually freed -- the check that catches a silent miss.
$stuck = $false
foreach ($port in 4200, 5000) {
    $listening = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    if ($listening) {
        $stuck = $true
        Write-Host ("WARNING: port {0} still LISTENING (PID {1})" -f $port, ($listening.OwningProcess -join ','))
    } else {
        Write-Host ("port {0} free" -f $port)
    }
}
if ($stuck) {
    Write-Host ""
    Write-Host "Ports still held - the uploader was NOT fully stopped."
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $elevated = (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $elevated) {
        Write-Host "This shell is NOT elevated. If the uploader was started from an"
        Write-Host "elevated terminal, Stop-Process gets Access Denied here (and its"
        Write-Host "CommandLine reads as null). Re-run this script as Administrator,"
        Write-Host "or just close/Ctrl+C the window that started it."
    }
}
