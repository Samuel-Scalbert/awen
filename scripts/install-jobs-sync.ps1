<#
.SYNOPSIS
    Installe la tache planifiee qui synchronise la veille emploi.

.DESCRIPTION
    Une synchronisation unique a heure fixe ne marche pas : le pipeline
    Claude cowork finit quand il finit. Un jour a 9h05, un autre a 12h47.
    Toute execution posterieure a l'heure choisie attendrait le lendemain.

    On installe donc une tache qui tourne toutes les 30 minutes de 7h a 23h.
    C'est sans cout : sync-jobs.ps1 compare une empreinte du dossier et
    n'ouvre le reseau que si quelque chose a bouge.

    Deux reglages comptent autant que la frequence :

      StartWhenAvailable   rattrape une execution manquee. Sans lui, un PC
                           en veille a 12h30 saute simplement le creneau.
      AllowStartIfOnBatteries  sinon Windows refuse silencieusement de
                           lancer la tache sur un portable debranche.

    Passe -Uninstall pour la retirer.

.EXAMPLE
    .\scripts\install-jobs-sync.ps1
    .\scripts\install-jobs-sync.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [string] $TaskName = 'Awen - sync veille emploi',
    [int]    $EveryMinutes = 30,
    [int]    $FromHour = 7,
    [int]    $ToHour = 23,
    [switch] $Uninstall
)

$ErrorActionPreference = 'Stop'

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Tache « $TaskName » supprimee."
    exit 0
}

$script = Join-Path $PSScriptRoot 'sync-jobs.ps1'
if (-not (Test-Path -LiteralPath $script)) {
    throw "sync-jobs.ps1 introuvable a cote de ce script : $script"
}

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass ' +
               "-File `"$script`"")

# Un declencheur quotidien porte la repetition ; on la fabrique via un
# declencheur -Once, seul moyen propre d'obtenir un objet Repetition.
$start = (Get-Date).Date.AddHours($FromHour)
$trigger = New-ScheduledTaskTrigger -Daily -At $start
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At $start `
    -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) `
    -RepetitionDuration (New-TimeSpan -Hours ($ToHour - $FromHour))).Repetition

# SANS CE PRINCIPAL, UNE FENETRE CLIGNOTE TOUTES LES 30 MINUTES.
#
# Par defaut la tache s'enregistre en LogonType Interactive : Windows lance
# alors powershell.exe DANS la session de bureau, et cree son hote de console
# avant que -WindowStyle Hidden n'ait le moindre effet. On voit donc une
# fenetre noire apparaitre et disparaitre, sans rapport apparent avec quoi
# que ce soit — le genre de symptome qu'on met des semaines a rattacher a sa
# cause.
#
# S4U (« Service For User ») execute la tache hors session interactive, et
# sans mot de passe a stocker, contrairement a Password. Le profil de
# l'utilisateur reste accessible, donc la cle SSH de ~/.ssh aussi.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
    -LogonType S4U -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force `
    -Description ('Pousse la veille emploi du pipeline Claude vers le ' +
                  'serveur Awen. Ne transfere que si le dossier a change.') | Out-Null

Write-Host "Tache « $TaskName » installee."
Write-Host ("Toutes les $EveryMinutes min, de ${FromHour}h a ${ToHour}h, " +
            'rattrapage si le PC etait eteint.')
Write-Host 'Elle tourne hors session : aucune fenetre ne doit apparaitre.'
Write-Host ''
Write-Host "Verifier    : Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "Lancer      : Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Desinstaller: .\scripts\install-jobs-sync.ps1 -Uninstall"
