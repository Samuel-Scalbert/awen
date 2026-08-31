<#
.SYNOPSIS
    Pousse la veille emploi du pipeline Claude cowork vers le serveur Awen.

.DESCRIPTION
    Le pipeline ecrit chaque matin sur le PC Windows, mais le serveur Debian
    ne voit pas ce disque. Ce script copie les deux seuls dossiers qu'Awen
    lit, via une archive tar transmise en SSH.

    On ne copie deliberement PAS tout le dossier de recherche d'emploi : les
    CV, notes d'entretien et PDF divers n'ont rien a faire sur le serveur.

.EXAMPLE
    .\scripts\sync-jobs.ps1
    .\scripts\sync-jobs.ps1 -RemoteHost 192.168.1.32 -Verbose
#>
[CmdletBinding()]
param(
    [string] $Source     = "$env:USERPROFILE\Claude\Projects\Recherche de CDI",
    [string] $RemoteHost = 'awen',
    [string] $RemoteDir  = '/srv/recherche-cdi'
)

$ErrorActionPreference = 'Stop'

# Les seuls dossiers lus par app/services/job_watch.py.
$Wanted = @('Veille quotidienne', 'Lettres de motivation')

if (-not (Test-Path -LiteralPath $Source)) {
    throw "Dossier source introuvable : $Source"
}

$present = @($Wanted | Where-Object { Test-Path -LiteralPath (Join-Path $Source $_) })
if ($present.Count -eq 0) {
    throw "Aucun des dossiers attendus dans $Source : $($Wanted -join ', ')"
}
Write-Verbose "A synchroniser : $($present -join ', ')"

# On passe par un fichier temporaire plutot qu'un pipe : le pipeline
# PowerShell transforme les octets en texte et corromprait l'archive.
$archive = Join-Path $env:TEMP 'awen-jobs.tar'

try {
    tar -cf $archive -C $Source $present
    if ($LASTEXITCODE -ne 0) { throw "tar a echoue (code $LASTEXITCODE)" }

    $size = [math]::Round((Get-Item $archive).Length / 1KB)
    Write-Verbose "Archive : $size Ko"

    scp -q $archive "${RemoteHost}:/tmp/awen-jobs.tar"
    if ($LASTEXITCODE -ne 0) { throw "scp a echoue (code $LASTEXITCODE)" }

    # tar ecrase les fichiers existants mais ne supprime rien : un compte
    # rendu efface par erreur cote Windows ne disparait pas du serveur.
    ssh $RemoteHost "mkdir -p '$RemoteDir' && tar -xf /tmp/awen-jobs.tar -C '$RemoteDir' && rm -f /tmp/awen-jobs.tar"
    if ($LASTEXITCODE -ne 0) { throw "extraction distante echouee (code $LASTEXITCODE)" }

    Write-Host "Veille emploi synchronisee vers ${RemoteHost}:${RemoteDir} ($size Ko)"
}
finally {
    Remove-Item $archive -ErrorAction SilentlyContinue
}
