# Gelistirme sunucusu (Windows PowerShell) -- start / stop / restart / status / logs
# Kullanim: .\run_dev.ps1 [start|stop|restart|status|logs|fg]
param(
    [string]$Action = "fg"
)

Set-Location $PSScriptRoot

$PidFile  = ".server.pid"
$LogFile  = "server.log"       # ana log (uvicorn + uygulama, stderr akisi)
$OutFile  = "server.out.log"   # ikincil (stdout akisi; genelde bos)
$VenvDir  = ".venv"
$VenvPy   = "$VenvDir\Scripts\python.exe"
$VenvPip  = "$VenvDir\Scripts\pip.exe"
$VenvAct  = "$VenvDir\Scripts\Activate.ps1"

# Uvicorn argumanlari.
# ONEMLI: --reload SADECE kaynak dizinlerini izler. Boylece proje kokune yazilan
# model dosyalari (*.pt), server.log, events.sqlite3, .server.pid gibi calisma-zamani
# ciktilari yeniden-baslatmayi (ve model indirme dongusunu) TETIKLEMEZ.
$UvicornArgs = @(
    "-m", "uvicorn", "backend.main:app",
    "--host", "0.0.0.0", "--port", "8000",
    "--reload",
    "--reload-dir", "backend",
    "--reload-dir", "ai",
    "--reload-dir", "config",
    "--reload-dir", "tools"
)

function Setup {
    if (-not (Test-Path $VenvDir)) {
        Write-Host ">> Sanal ortam olusturuluyor..."
        python -m venv $VenvDir
    }
    & $VenvPip install -q --upgrade pip
    & $VenvPip install -q -r requirements.txt
    if (-not $env:AI_MODE) { $env:AI_MODE = "auto" }

    # YOLO modellerini sunucu baslamadan ONCE indir/yukle.
    # Aksi halde gercek modda ilk indirme reload izleyicisini tetikleyip donguye sokar.
    # Not: betik gecici bir .py dosyasina yazilir; PowerShell 5.1 'python -c' icindeki
    # cift tirnaklari bozdugu icin -c kullanilmaz.
    if ($env:AI_MODE -ne "mock") {
        $prefetch = @'
try:
    from ultralytics import YOLO
    for m in ("yolov8n.pt", "yolov8s.pt"):
        YOLO(m)
    print("[OK] YOLO modelleri hazir")
except Exception as e:
    print("[i] Model on-indirme atlandi (mock moda dusulebilir):", e)
'@
        $tmpPy = Join-Path $env:TEMP "rg_prefetch_models.py"
        Set-Content -Path $tmpPy -Value $prefetch -Encoding UTF8
        & $VenvPy $tmpPy
        Remove-Item $tmpPy -ErrorAction SilentlyContinue
    }
}

function Banner {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 |
           Where-Object { $_.InterfaceAlias -notmatch 'Loopback' -and $_.IPAddress -notmatch '^169' } |
           Select-Object -First 1).IPAddress
    if (-not $ip) { $ip = "<IP>" }
    Write-Host ""
    Write-Host "================================================================"
    Write-Host "  Akilli Yol Guvenligi -- 5G & YZ Prototip"
    Write-Host "  Web dashboard :  http://localhost:8000/"
    Write-Host "  Telefondan    :  http://$($ip):8000/  (ayni Wi-Fi)"
    Write-Host "  Saglik        :  http://localhost:8000/api/health"
    Write-Host "================================================================"
    Write-Host ""
}

function IsRunning {
    if (-not (Test-Path $PidFile)) { return $false }
    $serverPid = Get-Content $PidFile -ErrorAction SilentlyContinue
    if (-not $serverPid) { return $false }
    return (Get-Process -Id $serverPid -ErrorAction SilentlyContinue) -ne $null
}

switch ($Action) {

    "start" {
        if (IsRunning) {
            $serverPid = Get-Content $PidFile
            Write-Host "[!] Sunucu zaten calisiyor (PID $serverPid)"
            exit 0
        }
        Setup
        Banner
        Write-Host ">> Sunucu arka planda baslatiliyor (log: $LogFile)..."
        $proc = Start-Process -FilePath $VenvPy `
            -ArgumentList $UvicornArgs `
            -RedirectStandardOutput $OutFile `
            -RedirectStandardError  $LogFile `
            -WindowStyle Hidden -PassThru
        $proc.Id | Set-Content $PidFile
        Start-Sleep -Seconds 2
        if (IsRunning) {
            Write-Host "[OK] Calisiyor (PID $($proc.Id))"
        } else {
            Write-Host "[X] Baslatilamadi -- son log:"
            Get-Content $LogFile -Tail 20
            exit 1
        }
    }

    "stop" {
        if (IsRunning) {
            $serverPid = Get-Content $PidFile
            # /T tum alt surecleri de oldurur. --reload modunda launcher bir reloader,
            # o da bir sunucu sureci dogurur; sadece ust PID'i oldurmek portu (8000)
            # tutan alt sureci OKSUZ birakir. /T /F ile tum agac temizlenir.
            taskkill /PID $serverPid /T /F 2>$null | Out-Null
            Remove-Item $PidFile -ErrorAction SilentlyContinue
            Write-Host "[OK] Durduruldu (PID $serverPid + alt surecler)"
        } else {
            Write-Host "[!] Calisan sunucu bulunamadi"
        }
    }

    "restart" {
        & $PSCommandPath stop
        Start-Sleep -Seconds 1
        & $PSCommandPath start
    }

    "status" {
        if (IsRunning) {
            $serverPid = Get-Content $PidFile
            Write-Host "[OK] Calisiyor (PID $serverPid)"
            Write-Host "   Log: $LogFile"
        } else {
            Write-Host "[X] Calismiyor"
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
        & $VenvPy @UvicornArgs
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
