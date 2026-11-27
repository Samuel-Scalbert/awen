<#
.SYNOPSIS
    Recap de fin de session Claude Code : ou on s'est arrete, et quoi ensuite.

.DESCRIPTION
    Appele par deux hooks Claude Code, installes par install-dev-recap.ps1 :

      Stop        -> -Mode journal   (a chaque reponse terminee)
      SessionEnd  -> -Mode finish    (quand la session se termine)

    Pourquoi deux hooks et pas seulement SessionEnd : SessionEnd ne part pas
    toujours (VS Code tue brutalement, PC qui s'eteint), et il partage un
    budget de 1,5 s par defaut. Le hook Stop tient donc un journal au fil de
    l'eau -- quelques millisecondes, zero reseau -- et SessionEnd ne fait que
    lancer la synthese en tache detachee avant de rendre la main aussitot.

    La synthese passe par `claude -p` sur le journal. Si le binaire manque ou
    repond de travers, on retombe sur un recap deterministe construit depuis
    git et le dernier message : un tableau de bord approximatif vaut mieux
    qu'un tableau de bord vide.

    Le recap est ecrit dans <projet>\.claude\recap\recap.json puis pousse
    vers Awen (POST /api/dev/recap). Serveur injoignable : le recap reste sur
    le disque et le prochain hook Stop reessaie.

.PARAMETER Mode
    journal | finish | synth | push | show

.EXAMPLE
    .\scripts\dev-recap.ps1 -Mode synth -Verbose    # synthetiser maintenant
    .\scripts\dev-recap.ps1 -Mode show              # voir le recap local
    .\scripts\dev-recap.ps1 -Mode push -Verbose     # repousser vers Awen
#>
[CmdletBinding()]
param(
    [ValidateSet('journal', 'finish', 'synth', 'push', 'show')]
    [string] $Mode    = 'show',
    [string] $Project = '',
    [string] $Server  = $(if ($env:AWEN_SERVER) { $env:AWEN_SERVER } else { 'http://192.168.1.32:5000' }),
    [string] $ApiKey  = $env:AWEN_DEV_API_KEY,
    [string] $Model   = 'haiku',
    [int]    $MaxEntries = 40
)

# Un hook qui plante ne doit jamais interrompre une session de code : on
# n'arrete donc rien sur erreur, chaque etape se protege elle-meme.
$ErrorActionPreference = 'Continue'
$ProgressPreference    = 'SilentlyContinue'

# --- Localisation du projet ------------------------------------------------

function Get-StdinJson {
    if (-not [Console]::IsInputRedirected) { return $null }
    try {
        $raw = [Console]::In.ReadToEnd()
        if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
        return $raw | ConvertFrom-Json
    } catch { return $null }
}

$stdin = $null
if ($Mode -in @('journal', 'finish')) { $stdin = Get-StdinJson }

if (-not $Project) {
    $Project = $env:CLAUDE_PROJECT_DIR
}
if (-not $Project -and $stdin -and $stdin.cwd) {
    $Project = [string] $stdin.cwd
}
if (-not $Project) { $Project = (Get-Location).Path }

# La racine git plutot que le cwd : une session lancee dans web/ ou src/ doit
# alimenter le meme recap que la racine du depot.
$root = $Project
try {
    $top = & git -C $Project rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -eq 0 -and $top) { $root = ($top -replace '/', '\').Trim() }
} catch { }

if (-not (Test-Path -LiteralPath $root)) {
    Write-Verbose "Racine introuvable : $root"
    exit 0
}

$slug       = Split-Path -Leaf $root
$recapDir   = Join-Path $root '.claude\recap'
$journalPath = Join-Path $recapDir 'journal.jsonl'
$recapPath  = Join-Path $recapDir 'recap.json'
$errorPath  = Join-Path $recapDir 'last-error.txt'
$null = New-Item -ItemType Directory -Force -Path $recapDir -ErrorAction SilentlyContinue

# --- Etat git -------------------------------------------------------------

function Get-GitState([switch] $WithDiff) {
    # Le hook Stop part a chaque reponse : on lui epargne le diffstat, de loin
    # l'appel git le plus cher. Seule la synthese en a besoin.
    $state = @{ branch = ''; dirty = 0; last_commit = ''; diffstat = '' }
    try {
        $branch = & git -C $root rev-parse --abbrev-ref HEAD 2>$null
        if ($LASTEXITCODE -eq 0) { $state.branch = ([string]$branch).Trim() }
        $porcelain = @(& git -C $root status --porcelain 2>$null)
        if ($LASTEXITCODE -eq 0) { $state.dirty = $porcelain.Count }
        $log = & git -C $root log -1 --pretty=format:'%h %s' 2>$null
        if ($LASTEXITCODE -eq 0) { $state.last_commit = ([string]$log).Trim() }
        if ($WithDiff) {
            $stat = @(& git -C $root diff --stat HEAD 2>$null) -join "`n"
            if ($LASTEXITCODE -eq 0) { $state.diffstat = $stat }
        }
    } catch { }
    return $state
}

function Limit-Text([string] $text, [int] $max) {
    if (-not $text) { return '' }
    $text = ($text -replace '\s+', ' ').Trim()
    if ($text.Length -le $max) { return $text }
    return $text.Substring(0, $max)
}

# --- Mode journal : une ligne par reponse terminee -------------------------

function Invoke-Journal {
    $git = Get-GitState
    $entry = [ordered]@{
        t       = (Get-Date).ToString('s')
        session = if ($stdin -and $stdin.session_id) { [string] $stdin.session_id } else { '' }
        msg     = Limit-Text ([string] $stdin.last_assistant_message) 1500
        branch  = $git.branch
        dirty   = $git.dirty
    }
    # JSONL : un ajout en fin de fichier, jamais de relecture ni de reecriture.
    # Deux sessions ouvertes en parallele peuvent ecrire sans se marcher dessus.
    try {
        Add-Content -LiteralPath $journalPath -Value ($entry | ConvertTo-Json -Compress) -Encoding UTF8
    } catch { }

    # Un envoi en attente ? On le rattrape ici : c'est le moment le moins
    # couteux pour reessayer, et ca evite une tache planifiee de plus.
    if (Test-Path -LiteralPath $recapPath) {
        $pending = Join-Path $recapDir 'pending-push'
        if (Test-Path -LiteralPath $pending) { Invoke-Push -Quiet }
    }
}

# --- Mode finish : detacher la synthese et rendre la main -----------------

function Invoke-Finish {
    # Le journal du tour courant peut manquer (SessionEnd peut partir avant
    # le dernier Stop) : on en pose un dernier si stdin en porte un.
    if ($stdin -and $stdin.last_assistant_message) { Invoke-Journal }

    if (-not (Test-Path -LiteralPath $journalPath)) {
        Write-Verbose 'Journal vide : rien a synthetiser.'
        return
    }
    $psArgs = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath,
        '-Mode', 'synth', '-Project', $root, '-Server', $Server, '-Model', $Model
    )
    if ($ApiKey) { $psArgs += @('-ApiKey', $ApiKey) }
    # Detache : la synthese dure plusieurs secondes, le hook SessionEnd a
    # 1,5 s. On lance et on sort.
    try {
        Start-Process -FilePath 'powershell.exe' -ArgumentList $psArgs -WindowStyle Hidden | Out-Null
    } catch {
        Write-Verbose "Lancement de la synthese impossible : $_"
    }
}

# --- Mode synth : journal + git -> recap.json ------------------------------

function Get-JournalTail {
    $lines = @()
    try { $lines = @(Get-Content -LiteralPath $journalPath -Encoding UTF8 -ErrorAction Stop) } catch { return @() }
    if ($lines.Count -gt $MaxEntries) { $lines = $lines[-$MaxEntries..-1] }
    $out = @()
    foreach ($l in $lines) {
        try { $out += ($l | ConvertFrom-Json) } catch { }
    }
    return $out
}

function New-FallbackRecap($entries, $git) {
    # Sans LLM : le dernier message dit ou on s'est arrete, le diffstat dit
    # sur quoi. Pas de "prochaines etapes" inventees -- un champ vide est
    # plus honnete qu'une liste devinee.
    $last = if ($entries.Count) { $entries[-1].msg } else { '' }
    return [ordered]@{
        project     = $slug
        branch      = $git.branch
        stopped_at  = Limit-Text $last 200
        done        = @()
        next        = @()
        blockers    = @('Synthese automatique indisponible : recap brut.')
        dirty       = $git.dirty
        last_commit = $git.last_commit
        host        = $env:COMPUTERNAME
    }
}

function Invoke-Synth {
    $git = Get-GitState -WithDiff
    $entries = Get-JournalTail
    if (-not $entries.Count) { Write-Verbose 'Journal illisible.'; return }

    $recap = $null
    $claude = Get-Command claude -ErrorAction SilentlyContinue
    if ($claude) {
        $transcript = ($entries | ForEach-Object { "[$($_.t)] $($_.msg)" }) -join "`n`n"
        $prompt = @"
Tu lis le journal d'une session de developpement sur le projet "$slug".
Chaque entree est le dernier message de l'assistant a la fin d'un tour.

Branche git : $($git.branch)
Dernier commit : $($git.last_commit)
Fichiers modifies non commites : $($git.dirty)
Diffstat :
$($git.diffstat)

Journal :
$transcript

Reponds UNIQUEMENT par un objet JSON, sans texte autour, sans bloc de code,
avec exactement ces cles :
{
  "stopped_at": "une phrase: ou on s'est arrete",
  "done":     ["ce qui a ete fait, 3 elements max, imperatif passe"],
  "next":     ["les prochaines choses a faire, 3 elements max, a l'imperatif"],
  "blockers": ["ce qui bloque ou reste incertain, 2 elements max, [] si rien"]
}
Chaque element fait moins de 90 caracteres. Ecris en francais, sans accents.
"@
        try {
            $raw = $prompt | & claude -p --model $Model 2>$null
            if ($LASTEXITCODE -eq 0 -and $raw) {
                $text = ($raw -join "`n")
                # Le modele ajoute parfois un bloc de code malgre la consigne.
                $m = [regex]::Match($text, '\{[\s\S]*\}')
                if ($m.Success) {
                    $parsed = $m.Value | ConvertFrom-Json
                    $recap = [ordered]@{
                        project     = $slug
                        branch      = $git.branch
                        stopped_at  = Limit-Text ([string] $parsed.stopped_at) 200
                        done        = @($parsed.done     | Where-Object { $_ } | Select-Object -First 3)
                        next        = @($parsed.next     | Where-Object { $_ } | Select-Object -First 3)
                        blockers    = @($parsed.blockers | Where-Object { $_ } | Select-Object -First 2)
                        dirty       = $git.dirty
                        last_commit = $git.last_commit
                        host        = $env:COMPUTERNAME
                    }
                }
            }
        } catch {
            Write-Verbose "claude -p a echoue : $_"
        }
    } else {
        Write-Verbose 'Binaire claude absent du PATH.'
    }

    if (-not $recap) { $recap = New-FallbackRecap $entries $git }

    try {
        $recap | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $recapPath -Encoding UTF8
    } catch {
        Write-Verbose "Ecriture du recap impossible : $_"
        return
    }

    # Le journal a servi : on l'archive pour que la prochaine session parte
    # d'une page blanche au lieu de resumer la semaine. On ne supprime rien,
    # le fichier precedent est juste ecrase.
    try {
        Move-Item -LiteralPath $journalPath -Destination (Join-Path $recapDir 'journal.prev.jsonl') -Force
    } catch { }

    Invoke-Push
}

# --- Envoi vers Awen ------------------------------------------------------

function Invoke-Push([switch] $Quiet) {
    $pending = Join-Path $recapDir 'pending-push'
    if (-not (Test-Path -LiteralPath $recapPath)) { return }
    if (-not $ApiKey) {
        if (-not $Quiet) { Write-Verbose 'AWEN_DEV_API_KEY non definie : recap garde en local.' }
        Set-Content -LiteralPath $pending -Value 'cle absente' -Encoding UTF8 -ErrorAction SilentlyContinue
        return
    }
    try {
        $body = Get-Content -LiteralPath $recapPath -Raw -Encoding UTF8
        $null = Invoke-RestMethod -Method Post -Uri "$Server/api/dev/recap" `
            -Headers @{ 'X-API-Key' = $ApiKey } -ContentType 'application/json; charset=utf-8' `
            -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 8
        # Le marqueur ne disparait qu'apres un envoi reussi : serveur eteint,
        # le prochain hook Stop reessaiera.
        if (Test-Path -LiteralPath $pending) {
            Set-Content -LiteralPath $pending -Value '' -Encoding UTF8 -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $pending -ErrorAction SilentlyContinue
        }
        if (-not $Quiet) { Write-Host "Recap de $slug pousse vers $Server" }
    } catch {
        Set-Content -LiteralPath $pending -Value "$(Get-Date -Format s) $_" -Encoding UTF8 -ErrorAction SilentlyContinue
        Set-Content -LiteralPath $errorPath -Value "$(Get-Date -Format s) $_" -Encoding UTF8 -ErrorAction SilentlyContinue
        if (-not $Quiet) { Write-Verbose "Envoi echoue : $_" }
    }
}

# --- Mode show ------------------------------------------------------------

function Invoke-Show {
    Write-Host "Projet : $slug"
    Write-Host "Racine : $root"
    if (Test-Path -LiteralPath $journalPath) {
        Write-Host "Journal : $(@(Get-Content -LiteralPath $journalPath).Count) entree(s)"
    } else { Write-Host 'Journal : aucun' }
    if (Test-Path -LiteralPath $recapPath) {
        Write-Host "--- $recapPath"
        Get-Content -LiteralPath $recapPath -Raw
    } else { Write-Host 'Recap : aucun (lancer -Mode synth)' }
    if (Test-Path -LiteralPath (Join-Path $recapDir 'pending-push')) {
        Write-Host 'Envoi en attente : oui'
        if (Test-Path -LiteralPath $errorPath) { Get-Content -LiteralPath $errorPath }
    }
}

switch ($Mode) {
    'journal' { Invoke-Journal }
    'finish'  { Invoke-Finish }
    'synth'   { Invoke-Synth }
    'push'    { Invoke-Push }
    'show'    { Invoke-Show }
}
exit 0
