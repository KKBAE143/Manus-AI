# =====================================================================
# dev-cleanup.ps1
#
# Aggressive cleanup helper used by dev-stop.bat / dev.bat.
#
# 1. Kills (with the full process tree) anything currently listening on
#    the given ports.
# 2. Kills any python.exe / node.exe / cmd.exe whose command line refers
#    to this project directory or to the uvicorn entrypoint we use, so
#    orphaned reloader children never survive a previous crash.
# =====================================================================

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectDir,

    [int[]]$Ports = @(8000, 5000)
)

# Normalize the project path (trailing slash stripped, full path)
$proj = (Resolve-Path -LiteralPath $ProjectDir).ProviderPath.TrimEnd('\')

function Stop-PidTree {
    param([int]$ProcessId)
    if (-not $ProcessId -or $ProcessId -le 0) { return }
    # taskkill /F /T walks the parent->child tree
    & taskkill.exe /F /T /PID $ProcessId 2>$null | Out-Null
}

# --- 1. Free the ports ------------------------------------------------
foreach ($port in $Ports) {
    $hits = netstat -ano | Select-String -Pattern (":$port\s.*LISTENING")
    foreach ($line in $hits) {
        $tokens = $line.Line.Trim() -split '\s+'
        if ($tokens.Count -ge 5) {
            $procId = [int]$tokens[$tokens.Count - 1]
            Write-Host "  killing tree of PID $procId on :$port"
            Stop-PidTree -ProcessId $procId
        }
    }
}

# --- 2. Find any process that still references our project ------------
# We collect every Win32_Process once (one cheap CIM call) then filter.
$all = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue

# Build a "self protection" set: this script's own pid plus every ancestor
# (cmd.exe / pwsh.exe / etc.) so we never kill ourselves mid-run.
$selfPids = New-Object System.Collections.Generic.HashSet[int]
$cur = $PID
while ($cur -gt 0) {
    if (-not $selfPids.Add([int]$cur)) { break }
    $parent = $all | Where-Object { $_.ProcessId -eq $cur } | Select-Object -First 1 -ExpandProperty ParentProcessId -ErrorAction SilentlyContinue
    if (-not $parent -or $parent -eq 0 -or $parent -eq $cur) { break }
    $cur = [int]$parent
}

# First pass: find processes whose command line mentions our project,
# *excluding* this script's own process tree.
$projOwners = @($all | Where-Object {
    $_.CommandLine -ne $null -and
    $_.CommandLine -like ('*' + $proj + '*') -and
    -not $selfPids.Contains([int]$_.ProcessId)
})

# Capture their PIDs so we can also kill orphaned multiprocessing.spawn
# children whose parents were already taken down.
$ownerPids = @{}
foreach ($p in $projOwners) { $ownerPids[$p.ProcessId] = $true }

# Second pass: collect everything to kill
$victims = New-Object System.Collections.Generic.HashSet[int]

foreach ($p in $projOwners) {
    [void]$victims.Add([int]$p.ProcessId)
}

foreach ($p in $all) {
    if ($null -eq $p.CommandLine) { continue }
    if ($selfPids.Contains([int]$p.ProcessId)) { continue }
    # Direct uvicorn entry point match (handles cases where the project
    # path didn't make it into the command line, e.g. when uvicorn was
    # launched through a wrapper).
    if ($p.CommandLine -match 'uvicorn\s+app\.main:app' -or
        $p.CommandLine -match 'app\.main:app.*--port\s+8000') {
        [void]$victims.Add([int]$p.ProcessId)
    }
    # Orphaned multiprocessing-fork children whose listed parent is one
    # of the project owners we're already killing.
    if ($p.CommandLine -match 'multiprocessing-fork' -and
        $ownerPids.ContainsKey([int]$p.ParentProcessId)) {
        [void]$victims.Add([int]$p.ProcessId)
    }
}

foreach ($vid in $victims) {
    # Resolve the name for nicer logs
    $proc = $all | Where-Object { $_.ProcessId -eq $vid } | Select-Object -First 1
    if ($proc) {
        Write-Host "  killing tree of PID $vid ($($proc.Name))"
    } else {
        Write-Host "  killing tree of PID $vid"
    }
    Stop-PidTree -ProcessId $vid
}

# Tiny grace period so Windows releases the sockets / file handles.
Start-Sleep -Milliseconds 400

# Final sanity check: are the ports still occupied?
foreach ($port in $Ports) {
    $still = netstat -ano | Select-String -Pattern (":$port\s.*LISTENING")
    if ($still) {
        Write-Host "  WARN :$port is still occupied after cleanup"
    }
}
