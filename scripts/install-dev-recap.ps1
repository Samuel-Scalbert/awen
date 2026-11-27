<#
.SYNOPSIS
    Installe (ou retire) les hooks de recap de fin de session Claude Code.

.DESCRIPTION
    Pose deux hooks dans <projet>\.claude\settings.json pour chaque projet
    passe en parametre :

      Stop        -> dev-recap.ps1 -Mode journal
      SessionEnd  -> dev-recap.ps1 -Mode finish

    Le script dev-recap.ps1 n'est PAS recopie dans chaque projet : les trois
    projets pointent vers la copie de ce depot, pour qu'une correction
    profite aux trois sans avoir a reinstaller.

    settings.json est fusionne, pas ecrase : d'autres hooks deja presents
    sont conserves. Relancer le script met simplement les chemins a jour.

    Ajoute aussi .claude/recap/ au .gitignore du projet (journal et recap
    sont un etat local) et une commande /recap pour synthetiser a la main.

.EXAMPLE
    .\scripts\install-dev-recap.ps1
    .\scripts\install-dev-recap.ps1 -Projects C:\Users\User\awen
    .\scripts\install-dev-recap.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    # awen n'est pas dans la liste par defaut : son depot vivant est ailleurs
    # que sous le dossier personnel, il se passe donc en parametre.
    #   .\install-dev-recap.ps1 -Projects "<chemin du depot awen>"
    [string[]] $Projects = @(
        "$env:USERPROFILE\ASVP_STATOR",
        "$env:USERPROFILE\Keychain_Manon"
    ),
    [string] $ScriptPath  = (Join-Path $PSScriptRoot 'dev-recap.ps1'),
    [string] $CommandPath = (Join-Path $PSScriptRoot 'recap-command.md'),
    [switch] $Uninstall
)

$ErrorActionPreference = 'Stop'

if (-not $Uninstall -and -not (Test-Path -LiteralPath $ScriptPath)) {
    throw "dev-recap.ps1 introuvable : $ScriptPath"
}
$ScriptPath = (Resolve-Path -LiteralPath $ScriptPath -ErrorAction SilentlyContinue).Path

function New-HookEntry([string] $mode, [int] $timeout) {
    $hook = [ordered]@{
        type    = 'command'
        command = 'powershell.exe'
        args    = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $ScriptPath, '-Mode', $mode)
    }
    if ($timeout -gt 0) { $hook.timeout = $timeout }
    return [ordered]@{ hooks = @($hook) }
}

# Reconnaitre NOS hooks parmi d'autres, pour pouvoir les remplacer ou les
# retirer sans toucher a ceux que tu ajouterais par ailleurs.
function Test-OurHook($group) {
    foreach ($h in @($group.hooks)) {
        if (($h.args -join ' ') -match 'dev-recap\.ps1') { return $true }
    }
    return $false
}

function Edit-Settings([string] $projectRoot) {
    $dir  = Join-Path $projectRoot '.claude'
    $path = Join-Path $dir 'settings.json'
    $settings = [ordered]@{}
    if (Test-Path -LiteralPath $path) {
        try {
            $existing = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
            # On repasse par un dictionnaire ordonne : ConvertFrom-Json rend
            # un PSCustomObject, peu pratique a modifier par cle.
            foreach ($p in $existing.PSObject.Properties) { $settings[$p.Name] = $p.Value }
        } catch {
            throw "settings.json illisible dans $projectRoot : corrige-le ou deplace-le."
        }
    }

    $hooks = [ordered]@{}
    if ($settings.Contains('hooks') -and $settings.hooks) {
        foreach ($p in $settings.hooks.PSObject.Properties) { $hooks[$p.Name] = @($p.Value) }
    }

    foreach ($evt in @('Stop', 'SessionEnd')) {
        $kept = @()
        if ($hooks.Contains($evt)) {
            $kept = @($hooks[$evt] | Where-Object { -not (Test-OurHook $_) })
        }
        if ($Uninstall) {
            if ($kept.Count) { $hooks[$evt] = $kept } else { $hooks.Remove($evt) }
        } else {
            # SessionEnd partage un budget de 1,5 s par defaut ; le timeout le
            # releve. Le hook se contente de detacher la synthese, 10 s suffisent.
            $timeout = if ($evt -eq 'SessionEnd') { 10 } else { 0 }
            $mode    = if ($evt -eq 'SessionEnd') { 'finish' } else { 'journal' }
            $hooks[$evt] = @($kept + @(New-HookEntry $mode $timeout))
        }
    }

    if ($hooks.Count) { $settings['hooks'] = $hooks } else { $settings.Remove('hooks') }

    if (-not $settings.Count) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
        return 'settings.json retire'
    }
    $null = New-Item -ItemType Directory -Force -Path $dir
    $settings | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $path -Encoding UTF8
    return 'settings.json a jour'
}

function Copy-RecapCommand([string] $projectRoot) {
    # La commande /recap vit a un seul endroit (scripts/recap-command.md) et
    # est recopiee : Claude Code ne lit les commandes que dans le projet.
    $target = Join-Path $projectRoot '.claude\commands\recap.md'
    if ($Uninstall) {
        if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target }
        return
    }
    if (-not (Test-Path -LiteralPath $CommandPath)) {
        Write-Warning "recap-command.md introuvable : $CommandPath"
        return
    }
    $null = New-Item -ItemType Directory -Force -Path (Split-Path $target)
    Copy-Item -LiteralPath $CommandPath -Destination $target -Force
}

function Edit-GitIgnore([string] $projectRoot) {
    $path = Join-Path $projectRoot '.gitignore'
    if (-not (Test-Path -LiteralPath $path)) { return }
    $lines = @(Get-Content -LiteralPath $path -Encoding UTF8)
    $marker = '.claude/recap/'
    if ($Uninstall) { return }
    if ($lines -contains $marker) { return }
    Add-Content -LiteralPath $path -Encoding UTF8 -Value @(
        '',
        '# Journal et recap de session Claude Code : etat local, pas versionne',
        $marker
    )
}

foreach ($p in $Projects) {
    if (-not (Test-Path -LiteralPath $p)) {
        Write-Warning "Projet introuvable, ignore : $p"
        continue
    }
    $root = (Resolve-Path -LiteralPath $p).Path
    $result = Edit-Settings $root
    Copy-RecapCommand $root
    Edit-GitIgnore $root
    Write-Host ("{0,-28} {1}" -f (Split-Path -Leaf $root), $result)
}

if (-not $Uninstall) {
    Write-Host ''
    Write-Host 'Reste a faire une seule fois :'
    Write-Host '  setx AWEN_DEV_API_KEY "<la cle DEV_API_KEY du .env serveur>"'
    Write-Host '  (puis rouvrir VS Code pour que la variable soit vue)'
}
