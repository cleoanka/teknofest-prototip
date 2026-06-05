# Geliştirme sunucusu (Windows PowerShell) — start / stop / restart / status / logs
# Kullanim: .\run_dev.ps1 [start|stop|restart|status|logs|fg]
param(
    [string]$Action = "fg"
)

Set-Location $PSScriptRoot

$PidFile  = ".server.pid"
$LogFile  = "server.log"
$VenvDir  = ".venv"
$VenvPy   = "$VenvDir\Scripts\python.exe"
$VenvPip  = "$VenvDir\Scripts\pip.exe"
$VenvAct  = "$VenvDir\Scripts\Activate.ps1"
$UvicornCmd = "python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload"

function Setup {
    if (-not (Test-Path $VenvDir)) {
        Write-Host "» Sanal ortam olusturuluyor..."
        python -m venv $VenvDir
    }
    & $VenvPip install -q --upgrade pip
    & $VenvPip install -q -r requirements.txt
    if (-not $env:AI_MODE) { $env:AI_MODE = "auto" }
}

function Banner {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 |
           Where-Object { $_.InterfaceAlias -notmatch 'Loopback' -and $_.IPAddress -notmatch '^169' } |
           Select-Object -First 1).IPAddress
    Write-Host ""
    Write-Host "================================================================"
    Write-Host "  Akilli Yol Guvenligi -- 5G & YZ Prototip"
    Write-Host "  Web dashboard :  http://localhost:8000/"
    Write-Host "  Telefondan    :  http://$($ip ?? '<IP>'):8000/  (ayni Wi-Fi)"
    Write-Host "  Saglik        :  http://localhost:8000/api/health"
    Write-Host "================================================================"
    Write-Host ""
}

function IsRunning {
    if (-not (Test-Path $PidFile)) { return $false }
    $pid = Get-Content $PidFile -ErrorAction SilentlyContinue
    if (-not $pid) { return $false }
    return (Get-Process -Id $pid -ErrorAction SilentlyContinue) -ne $null
}

switch ($Action) {

    "start" {
        if (IsRunning) {
            $pid = Get-Content $PidFile
            Write-Host "⚠  Sunucu zaten calisiyor (PID $pid)"
            exit 0
        }
        Setup
        Banner
        Write-Host "» Sunucu arka planda baslatiliyor (log: $LogFile)..."
        $proc = Start-Process -FilePath $VenvPy `
            -ArgumentList "-m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload" `
            -RedirectStandardOutput $LogFile `
            -RedirectStandardError  $LogFile `
            -WindowStyle Hidden -PassThru
        $proc.Id | Set-Content $PidFile
        Start-Sleep -Seconds 2
        if (IsRunning) {
            Write-Host "✓  Calisiyor (PID $($proc.Id))"
        } else {
            Write-Host "✗  Baslatılamadi -- son log:"
            Get-Content $LogFile -Tail 20
            exit 1
        }
    }

    "stop" {
        if (IsRunning) {
            $pid = Get-Content $PidFile
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
            Remove-Item $PidFile -ErrorAction SilentlyContinue
            Write-Host "✓  Durduruldu (PID $pid)"
        } else {
            Write-Host "⚠  Calisan sunucu bulunamadi"
        }
    }

    "restart" {
        & $PSCommandPath stop
        Start-Sleep -Seconds 1
        & $PSCommandPath start
    }

    "status" {
        if (IsRunning) {
            $pid = Get-Content $PidFile
            Write-Host "✓  Calisiyor (PID $pid)"
            Write-Host "   Log: $LogFile"
        } else {
            Write-Host "✗  Calismiyor"
        }
    }

    "logs" {
        if (Test-Path $LogFile) {
            Get-Content $LogFile -Wait -Tail 30
        } else {
            Write-Host "Log dosyasi yok: $LogFile"
        }
    }

    { $_ -in "fg", "" } {
        Setup
        Banner
        & $VenvPy -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
    }

    default {
        Write-Host "Kullanim: .\run_dev.ps1 [start|stop|restart|status|logs|fg]"
        Write-Host ""
        Write-Host "  start    -- arka planda baslatir (log: $LogFile)"
        Write-Host "  stop     -- durdurur"
        Write-Host "  restart  -- yeniden baslatir"
        Write-Host "  status   -- calisiyor mu?"
        Write-Host "  logs     -- canli log takibi"
        Write-Host "  fg       -- on planda baslatir (varsayilan)"
        exit 1
    }
}
