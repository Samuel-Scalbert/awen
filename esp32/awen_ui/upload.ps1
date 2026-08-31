<#
.SYNOPSIS
    Televerse le firmware Awen sur l'ESP32 et ouvre la console.

.DESCRIPTION
    Copie les fichiers de ce dossier sur la carte, puis la redemarre. Sans
    -Port, le script cherche tout seul le seul port serie disponible.

    Il NE copie PAS st7789_min.py, tft_setup.py ni wifi.py : ceux-la viennent
    du depot esp32-desk-display et doivent deja etre sur la carte. Le script
    verifie leur presence et refuse de continuer s'ils manquent, plutot que de
    te laisser decouvrir un ImportError sur un ecran noir.

.EXAMPLE
    .\upload.ps1
    .\upload.ps1 -Port COM5
    .\upload.ps1 -Console        # televerse puis affiche la sortie de la carte
#>
[CmdletBinding()]
param(
    [string] $Port,
    [switch] $Console
)

$ErrorActionPreference = 'Stop'

$Files = @('theme.py', 'grid.py', 'input.py', 'screens.py', 'app.py',
           'main.py', 'awen_config.py')
$Required = @('st7789_min.py', 'tft_setup.py', 'wifi.py')

# --- mpremote ---------------------------------------------------------------
function Invoke-Mpremote {
    param([Parameter(ValueFromRemainingArguments)] $Args)
    if (Get-Command mpremote -ErrorAction Ignore) {
        & mpremote @Args
    } else {
        & python -m mpremote @Args
    }
}

$hasTool = (Get-Command mpremote -ErrorAction Ignore) -or
           (python -c "import mpremote" 2>$null; $LASTEXITCODE -eq 0)
if (-not $hasTool) {
    Write-Host "mpremote est absent. Installe-le une fois :" -ForegroundColor Yellow
    Write-Host '    pip install mpremote'
    exit 1
}

# --- fichiers locaux --------------------------------------------------------
Push-Location $PSScriptRoot
try {
    $missing = $Files | Where-Object { -not (Test-Path -LiteralPath $_) }
    if ($missing) {
        if ($missing -contains 'awen_config.py') {
            Write-Host 'awen_config.py manque. Cree-le une fois :' -ForegroundColor Yellow
            Write-Host '    Copy-Item awen_config.example.py awen_config.py'
            Write-Host '    notepad awen_config.py     # wifi + URL + cle API'
            exit 1
        }
        throw "Fichiers introuvables : $($missing -join ', ')"
    }

    # --- port -------------------------------------------------------------
    if (-not $Port) {
        $ports = [System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object
        if ($ports.Count -eq 0) {
            Write-Host 'Aucun port serie. La carte est-elle branchee en USB ?' -ForegroundColor Yellow
            Write-Host 'Certains cables USB ne transportent que le courant : essaie-en un autre.'
            exit 1
        }
        if ($ports.Count -gt 1) {
            Write-Host "Plusieurs ports : $($ports -join ', ')" -ForegroundColor Yellow
            Write-Host 'Precise lequel :  .\upload.ps1 -Port COM5'
            exit 1
        }
        $Port = $ports[0]
    }
    Write-Host "Carte sur $Port" -ForegroundColor Cyan

    # --- dependances deja sur la carte -------------------------------------
    $onBoard = (Invoke-Mpremote connect $Port fs ls) -join "`n"
    if ($LASTEXITCODE -ne 0) {
        throw "Impossible de parler a la carte sur $Port. Ferme Thonny ou tout autre programme qui tient le port."
    }
    $absent = $Required | Where-Object { $onBoard -notmatch [regex]::Escape($_) }
    if ($absent) {
        Write-Host "Il manque sur la carte : $($absent -join ', ')" -ForegroundColor Yellow
        Write-Host 'Ils viennent du depot esp32-desk-display (dossier micropython/).'
        exit 1
    }

    # --- televersement -------------------------------------------------------
    foreach ($f in $Files) {
        Write-Host "  -> $f"
        Invoke-Mpremote connect $Port fs cp $f ":$f" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "echec de la copie de $f" }
    }

    Write-Host 'Redemarrage...' -ForegroundColor Cyan
    Invoke-Mpremote connect $Port reset | Out-Null

    if ($Console) {
        Write-Host 'Console de la carte (Ctrl-] pour quitter)' -ForegroundColor Cyan
        Start-Sleep -Milliseconds 500
        Invoke-Mpremote connect $Port repl
    } else {
        Write-Host ''
        Write-Host 'Fait. Pour voir ce que raconte la carte :' -ForegroundColor Green
        Write-Host "    .\upload.ps1 -Port $Port -Console"
    }
}
finally {
    Pop-Location
}
