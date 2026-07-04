param(
    [string]$Action = "up"
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Root  # go up to Vibe-Trading

$BackendHost = "127.0.0.1"
$BackendPort = "8899"
$FrontendHost = "127.0.0.1"
$FrontendPort = "5899"

$StateDir = Join-Path $Root ".vibe-dev"
$LogDir = Join-Path $StateDir "logs"
$PidDir = Join-Path $StateDir "pids"

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
New-Item -ItemType Directory -Path $PidDir -Force | Out-Null

function Get-ServiceUrl($Service) {
    if ($Service -eq "backend") { return "http://$BackendHost`:$BackendPort/health" }
    if ($Service -eq "frontend") { return "http://$FrontendHost`:$FrontendPort" }
}

function Test-ServiceUrl($Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

function Start-Backend {
    $pidFile = Join-Path $PidDir "backend.pid"
    $logFile = Join-Path $LogDir "backend.log"
    
    if (Test-Path $pidFile) {
        $existingPid = Get-Content $pidFile
        if (Get-Process -Id $existingPid -ErrorAction SilentlyContinue) {
            Write-Host "backend already running (pid $existingPid)"
            return
        }
    }
    
    if (Test-ServiceUrl (Get-ServiceUrl "backend")) {
        Write-Host "backend already reachable at $(Get-ServiceUrl 'backend')"
        Remove-Item $pidFile -ErrorAction SilentlyContinue
        return
    }
    
    Write-Host "starting backend..."
    $env:PYTHONPATH = Join-Path $Root "agent"
    $proc = Start-Process -FilePath "python" `
        -ArgumentList "-c", "import cli, sys; raise SystemExit(cli.main(sys.argv[1:]))", "serve", "--host", $BackendHost, "--port", $BackendPort `
        -WorkingDirectory (Join-Path $Root "agent") `
        -RedirectStandardOutput $logFile `
        -RedirectStandardError $logFile `
        -NoNewWindow `
        -PassThru
    
    $proc.Id | Out-File -FilePath $pidFile -Encoding ascii
    Write-Host "backend pid $($proc.Id), log $logFile"
}

function Start-Frontend {
    $pidFile = Join-Path $PidDir "frontend.pid"
    $logFile = Join-Path $LogDir "frontend.log"
    
    if (Test-Path $pidFile) {
        $existingPid = Get-Content $pidFile
        if (Get-Process -Id $existingPid -ErrorAction SilentlyContinue) {
            Write-Host "frontend already running (pid $existingPid)"
            return
        }
    }
    
    if (Test-ServiceUrl (Get-ServiceUrl "frontend")) {
        Write-Host "frontend already reachable at $(Get-ServiceUrl 'frontend')"
        Remove-Item $pidFile -ErrorAction SilentlyContinue
        return
    }
    
    $frontendDir = Join-Path $Root "frontend"
    if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
        Push-Location $frontendDir
        npm install
        Pop-Location
    }
    
    Write-Host "starting frontend..."
    $env:VITE_API_URL = "http://$BackendHost`:$BackendPort"
    $proc = Start-Process -FilePath "npm" `
        -ArgumentList "run", "dev", "--", "--host", $FrontendHost, "--port", $FrontendPort `
        -WorkingDirectory $frontendDir `
        -RedirectStandardOutput $logFile `
        -RedirectStandardError $logFile `
        -NoNewWindow `
        -PassThru
    
    $proc.Id | Out-File -FilePath $pidFile -Encoding ascii
    Write-Host "frontend pid $($proc.Id), log $logFile"
}

function Stop-All {
    foreach ($service in @("frontend", "backend")) {
        $pidFile = Join-Path $PidDir "$service.pid"
        if (Test-Path $pidFile) {
            $pid = Get-Content $pidFile
            if (Get-Process -Id $pid -ErrorAction SilentlyContinue) {
                Write-Host "stopping $service (pid $pid)..."
                Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
            }
            Remove-Item $pidFile -ErrorAction SilentlyContinue
        }
    }
}

function Show-Status {
    foreach ($service in @("backend", "frontend")) {
        $pidFile = Join-Path $PidDir "$service.pid"
        $running = $false
        if (Test-Path $pidFile) {
            $pid = Get-Content $pidFile
            $running = [bool](Get-Process -Id $pid -ErrorAction SilentlyContinue)
        }
        
        if ($running) {
            Write-Host "$service`trunning`tpid=$pid"
        } elseif (Test-ServiceUrl (Get-ServiceUrl $service)) {
            Write-Host "$service`treachable`tturl=$(Get-ServiceUrl $service)"
        } else {
            Write-Host "$service` stopped"
        }
    }
}

switch ($Action) {
    "up" {
        Start-Backend
        Start-Frontend
        Write-Host ""
        Write-Host "Frontend: http://127.0.0.1:$FrontendPort"
        Write-Host "Backend:  http://127.0.0.1:$BackendPort"
    }
    "stop" { Stop-All }
    "status" { Show-Status }
    default { Write-Host "Usage: dev_up.ps1 [up|stop|status]" }
}
