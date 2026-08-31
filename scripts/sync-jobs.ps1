<#
.SYNOPSIS
    Pousse la veille emploi du pipeline Claude cowork vers le serveur Awen.

.DESCRIPTION
    Le pipeline ecrit chaque matin sur le PC Windows, mais le serveur Debian
    ne voit pas ce disque. Ce script copie les deux seuls dossiers qu'Awen
    lit, via une archive tar transmise en SSH.

    On ne copie deliberement PAS tout le dossier de recherche d'emploi : les
    CV, notes d'entretien et PDF divers n'ont rien a faire sur le serveur.

    Le script est concu pour tourner TRES souvent (toutes les 30 minutes).
    Il calcule une empreinte du contenu et ne transfere rien quand rien n'a
    bouge : une execution a vide coute quelques millisecondes et zero reseau.
    C'est ce qui permet de ne plus dependre de l'heure a laquelle le pipeline
    se termine.

.EXAMPLE
    .\scripts\sync-jobs.ps1
    .\scripts\sync-jobs.ps1 -Verbose
    .\scripts\sync-jobs.ps1 -Force        # transfere meme sans changement
#>
[CmdletBinding()]
param(
    [string] $Source     = "$env:USERPROFILE\Claude\Projects\Recherche de CDI",
    [string] $RemoteHost = 'awen',
    [string] $RemoteDir  = '/srv/recherche-cdi',
    [switch] $Force
)

$ErrorActionPreference = 'Stop'

# Les seuls dossiers lus par app/services/job_watch.py.
$Wanted = @('Veille quotidienne', 'Lettres de motivation')

# L'empreinte du dernier envoi reussi. Hors du depot : c'est un etat local,
# propre a cette machine, pas quelque chose a versionner.
$StateFile = Join-Path $env:LOCALAPPDATA 'awen-sync-jobs.state'

if (-not (Test-Path -LiteralPath $Source)) {
    throw "Dossier source introuvable : $Source"
}

$present = @($Wanted | Where-Object { Test-Path -LiteralPath (Join-Path $Source $_) })
if ($present.Count -eq 0) {
    throw "Aucun des dossiers attendus dans $Source : $($Wanted -join ', ')"
}
Write-Verbose "A synchroniser : $($present -join ', ')"

# --- Rien de neuf ? On s'arrete avant de toucher au reseau. ----------------
#
# L'empreinte combine nombre de fichiers, taille totale et date de
# modification la plus recente. Un fichier ajoute, modifie ou supprime la
# change forcement ; deux executions d'affilee sans changement ne la changent
# jamais.
$files = foreach ($d in $present) {
    Get-ChildItem -LiteralPath (Join-Path $Source $d) -Recurse -File -ErrorAction SilentlyContinue
}
$count = ($files | Measure-Object).Count
$bytes = ($files | Measure-Object -Property Length -Sum).Sum
$newest = ($files | Measure-Object -Property LastWriteTimeUtc -Maximum).Maximum
$fingerprint = "$count|$bytes|$($newest.Ticks)"
Write-Verbose "Empreinte : $fingerprint"

if (-not $Force -and (Test-Path -LiteralPath $StateFile)) {
    if ((Get-Content -LiteralPath $StateFile -Raw).Trim() -eq $fingerprint) {
        Write-Verbose 'Aucun changement depuis le dernier envoi : rien a faire.'
        exit 0
    }
}

# --- Transfert -------------------------------------------------------------
#
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

    # L'empreinte n'est enregistree qu'apres un envoi reussi : si le serveur
    # dort, la prochaine execution reessaiera au lieu de croire le travail
    # fait.
    Set-Content -LiteralPath $StateFile -Value $fingerprint -NoNewline

    Write-Host "Veille emploi synchronisee vers ${RemoteHost}:${RemoteDir} ($count fichiers, $size Ko)"
}
finally {
    Remove-Item $archive -ErrorAction SilentlyContinue
}
