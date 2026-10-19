"""Lettres de motivation : Claude écrit, Samuel corrige, Claude apprend.

LE CONTEXTE VIENT DU PROJET « RECHERCHE DE CDI »

Les règles sont celles de la section 8 des instructions de la veille, la
structure celle du modèle, le ton celui des lettres déjà envoyées, et les
faits ceux de la fiche profil et du CV ATS. Rien de tout cela n'est recopié
ici : on lit les fichiers que scripts/sync-jobs.ps1 pousse sur le serveur.
Quand Samuel corrige sa fiche profil, la lettre suivante le sait.

Ces sources forment le message système, identique d'une lettre à l'autre :
il est mis en cache, et seule l'offre se paie au prix plein.

APPRENDRE DES CORRECTIONS

Chaque lettre garde le brouillon de Claude à côté de la version corrigée.
À l'export du PDF, si Samuel a vraiment réécrit quelque chose, Claude compare
les deux et en tire au plus trois règles générales. Elles entrent dans
toutes les lettres suivantes, avec les deux dernières corrections montrées
telles quelles. Les règles s'affichent sur la page des lettres et se
retirent d'un clic : une leçon fausse appliquée en silence serait pire que
pas de leçon.

LA GÉNÉRATION TOURNE EN ARRIÈRE-PLAN

Une lettre prend une demi-minute à une minute. Gunicorn coupe une requête
au bout de 120 secondes : on ne la fait donc pas attendre. La page lance la
génération, puis demande l'état toutes les deux secondes.

DEUX MOTEURS, UN SEUL SKILL

La façon d'écrire vit dans un skill Claude Code,
.claude/skills/lettre-motivation/SKILL.md : les règles, la méthode, le
format. Il se retouche comme un texte, et sert aussi bien à la main dans
Claude Code qu'au bouton d'Awen. Deux moteurs l'exécutent :

- « abonnement » : Claude Code, installé dans l'image, tourne sans
  interface avec l'abonnement Claude de Samuel (jeton créé par
  `claude setup-token`). Aucun frais en plus ; l'usage compte dans les
  limites de l'abonnement.
- « api » : l'API Claude, facturée à l'usage (ANTHROPIC_API_KEY).

Avec un jeton d'abonnement, c'est lui qui sert ; LETTRE_MOTEUR force l'un ou
l'autre.
"""
import difflib
import hashlib
import html
import json
import os
import re
import subprocess
import tempfile
import threading
import unicodedata
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from flask import current_app

from ..models import CoverLetter, LetterLesson, db
from .job_watch import get_daily_reports

MODELE = "claude-opus-5-5"
EFFORT = "high"
# Repli côté serveur si un classifieur de sécurité refuse la demande : la
# même requête repart sur le modèle que recommande Anthropic pour ce cas.
BETAS = ["server-side-fallback-2026-07-01"]

FICHE = "Fiche profil - Samuel Scalbert.md"
SUIVI = "Suivi des candidatures.md"
CV = "_CV ATS (source modifiable).html"
INSTRUCTIONS = "_Instructions veille PO (tache quotidienne).md"
DOSSIER = "Lettres de motivation"
GABARIT = "_Modele de lettre (template).md"

# Le skill qui dit comment écrire : le même pour les deux moteurs.
SKILL = (Path(__file__).resolve().parents[2]
         / ".claude" / "skills" / "lettre-motivation" / "SKILL.md")
# Claude Code met deux à quatre minutes ; au-delà de dix, il est bloqué.
DELAI_CLAUDE_CODE = 600

EXEMPLES = 2            # lettres montrées pour le ton
# Du moins coûteux au plus approfondi : un plafond d'effort se compare ici.
EFFORTS = ("low", "medium", "high", "xhigh", "max")
CORRECTIONS = 2         # dernières corrections montrées telles quelles
SEUIL_LECON = 0.97      # au-delà de cette ressemblance, rien à apprendre
# Un appel dure au pire 5 minutes, trois fois avec les nouvelles tentatives.
# Passé ce délai, le fil qui écrivait la lettre n'existe plus.
ABANDON = timedelta(minutes=20)

SCHEMA_LETTRE = {
    "type": "object",
    "properties": {
        "entreprise": {"type": "string"},
        "poste": {"type": "string"},
        "destinataire": {"type": "array", "items": {"type": "string"}},
        "objet": {"type": "string"},
        "salutation": {"type": "string"},
        "paragraphes": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["entreprise", "poste", "destinataire", "objet",
                 "salutation", "paragraphes", "notes"],
    "additionalProperties": False,
}

SCHEMA_LECONS = {
    "type": "object",
    "properties": {"lecons": {"type": "array", "items": {"type": "string"}}},
    "required": ["lecons"],
    "additionalProperties": False,
}


class LettreErreur(Exception):
    """Une erreur à montrer telle quelle à Samuel, en français."""


class LettreTropLongue(LettreErreur):
    def __init__(self, lignes):
        self.lignes = lignes
        super().__init__(
            "La lettre dépasse une page d'environ {} ligne{} : raccourcis-la "
            "avant d'exporter.".format(lignes, "s" if lignes > 1 else ""))


# --------------------------------------------------------------------------
# Les sources


def _racine():
    root = current_app.config.get("JOB_SEARCH_DIR") or ""
    p = Path(root)
    return p if root and p.is_dir() else None


def _lire(*parts):
    base = _racine()
    if base is None:
        return None
    f = base.joinpath(*parts)
    try:
        return f.read_text(encoding="utf-8") if f.is_file() else None
    except (OSError, UnicodeDecodeError):
        return None


def _section_lettres(instructions):
    """La section 8 des instructions de la veille : les règles des lettres."""
    m = re.search(r"^###\s*8\..*?(?=^###\s|\Z)", instructions or "", re.S | re.M)
    return m.group(0).strip() if m else ""


def _texte_html(source):
    """Le CV ATS est une page HTML : on n'en garde que le texte."""
    s = re.sub(r"(?is)<(style|script|head)\b.*?</\1>", " ", source or "")
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    lignes = [" ".join(l.split()) for l in s.splitlines()]
    return "\n".join(l for l in lignes if l)


def _corps_lettre(texte):
    """Une lettre .md du dossier : la lettre commence après la ligne « --- »."""
    parts = re.split(r"^---\s*$", texte or "", maxsplit=1, flags=re.M)
    return (parts[1] if len(parts) > 1 else parts[0]).strip()


def _cle(nom):
    """« JCDecaux », « Hermès (Pantin) » : sans accents, casse ni précision."""
    nom = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    return nom.split("(")[0].strip().lower()


def _reussies():
    """Les entreprises où la candidature a obtenu un entretien, d'après la
    colonne Notes du suivi des candidatures."""
    out = set()
    for ligne in (_lire(SUIVI) or "").splitlines():
        cols = [c.strip() for c in ligne.strip().strip("|").split("|")]
        if len(cols) >= 6 and re.search(r"entretien", cols[-1], re.I):
            out.add(_cle(cols[1]))
    return out


def _exemples():
    """Les lettres montrées pour le ton : celles qui ont obtenu un entretien.

    Les dernières écrites n'ont rien prouvé ; celles qui ont décroché un
    entretien, si. À défaut de suivi, les plus récentes.
    """
    base = _racine()
    if base is None:
        return []
    dossier = base / DOSSIER
    if not dossier.is_dir():
        return []
    fichiers = sorted(
        (f for f in dossier.glob("*.md")
         if f.is_file() and not f.name.startswith("_")),
        key=lambda f: f.stat().st_mtime, reverse=True)
    reussies = _reussies()
    choisies = [f for f in fichiers if _cle(f.stem.split(" - ")[0]) in reussies]
    out = []
    for f in (choisies or fichiers)[:EXEMPLES]:
        try:
            out.append((f.stem, _corps_lettre(f.read_text(encoding="utf-8"))))
        except (OSError, UnicodeDecodeError):
            continue
    return out


def sources():
    """Tout ce que Claude lit avant d'écrire, et ce qui manque."""
    regles = _section_lettres(_lire(INSTRUCTIONS))
    data = {
        "regles": regles,
        "gabarit": _corps_lettre(_lire(DOSSIER, GABARIT) or ""),
        "profil": (_lire(FICHE) or "").strip(),
        "cv": _texte_html(_lire(CV)),
        "exemples": _exemples(),
    }
    data["manquants"] = [nom for nom, cle in (
        ("la fiche profil", "profil"), ("le CV ATS", "cv"),
        ("les règles des lettres (instructions de la veille)", "regles"),
        ("le modèle de lettre", "gabarit")) if not data[cle]]
    return data


def expediteur_par_defaut():
    """L'en-tête de la dernière lettre, sinon celui du modèle.

    Corrigé une fois dans l'éditeur, il suit toutes les lettres suivantes :
    pas de réglage à chercher ailleurs.
    """
    derniere = (CoverLetter.query.filter(CoverLetter.expediteur != "")
                .order_by(CoverLetter.id.desc()).first())
    if derniere is not None:
        return derniere.expediteur
    gabarit = _corps_lettre(_lire(DOSSIER, GABARIT) or "")
    bloc = gabarit.split("\n\n", 1)[0].strip()
    return bloc if "[" not in bloc else ""


def date_du_jour(jour=None):
    jour = jour or date.today()
    return "{:%d/%m/%Y} - Paris".format(jour)


def offres_recentes(jours=10):
    """Les offres retenues par la veille, pour les choisir sans recopier."""
    out = []
    for r in get_daily_reports(limit=jours) or []:
        for i, o in enumerate(r["offers"]):
            ref = "{}#{}".format(r["dirname"], o.get("rank") or i + 1)
            entreprise = o.get("company") or ""
            poste = o.get("role") or o.get("title") or ""
            out.append({
                "ref": ref,
                "label": "{} : {}{}".format(
                    r.get("day_short") or r["dirname"], poste,
                    " ({})".format(entreprise) if entreprise else ""),
                "entreprise": entreprise,
                "poste": poste,
                "texte": "{}\n\n{}".format(o.get("title", ""),
                                           o.get("body", "")).strip(),
            })
    return out


# --------------------------------------------------------------------------
# Le prompt


SYSTEME = """{consignes}

# Les sources

<regles>
{regles}
</regles>

<modele>
{gabarit}
</modele>

<fiche_profil>
{profil}
</fiche_profil>

<cv>
{cv}
</cv>

<lettres_envoyees>
{exemples}
</lettres_envoyees>"""

DEMANDE = """<offre{ref}>
{offre}
</offre>

<priorites_de_samuel>
{priorites}
</priorites_de_samuel>
{lecons}{corrections}
Écris la lettre pour cette offre. Les priorités de Samuel passent avant tes propres choix : chacune doit se retrouver explicitement dans la lettre. Si l'offre ne donne aucun élément concret sur l'entreprise, prends le plus précis qu'elle contienne et signale-le dans les notes."""


def consignes():
    """Le corps du skill, sans son en-tête : relu à chaque lettre, pour
    qu'une retouche serve dès la suivante."""
    try:
        texte = SKILL.read_text(encoding="utf-8")
    except OSError:
        raise LettreErreur("Le skill des lettres est introuvable ({}).".format(SKILL))
    morceaux = re.split(r"^---\s*$", texte, maxsplit=2, flags=re.M)
    return (morceaux[2] if texte.startswith("---") and len(morceaux) == 3
            else texte).strip()


def _systeme(src):
    exemples = "\n\n".join(
        '<lettre titre="{}">\n{}\n</lettre>'.format(escape(t), c)
        for t, c in src["exemples"]) or "(aucune)"
    return SYSTEME.format(consignes=consignes(), regles=src["regles"],
                          gabarit=src["gabarit"], profil=src["profil"],
                          cv=src["cv"], exemples=exemples)


def _lecons_actives():
    return LetterLesson.query.filter_by(active=True).order_by(
        LetterLesson.id).all()


def _corrigees(sauf=None):
    """Les dernières lettres que Samuel a vraiment réécrites."""
    out = []
    q = (CoverLetter.query.filter(CoverLetter.exportee_le.isnot(None))
         .order_by(CoverLetter.exportee_le.desc()))
    for l in q.limit(10):
        if l.id == sauf:
            continue
        avant = _texte_brouillon(l)
        if avant and _ressemblance(avant, _texte_final(l)) < SEUIL_LECON:
            out.append(l)
        if len(out) >= CORRECTIONS:
            break
    return out


def _demande(lettre):
    lecons = _lecons_actives()
    bloc_lecons = ""
    if lecons:
        bloc_lecons = "\n<lecons>\nCe que Samuel a corrigé dans les lettres précédentes, à appliquer :\n{}\n</lecons>\n".format(
            "\n".join("- " + l.texte for l in lecons))
    bloc_corr = ""
    corr = _corrigees(sauf=lettre.id)
    if corr:
        bloc_corr = "\n<corrections_recentes>\n{}\n</corrections_recentes>\n".format(
            "\n\n".join(
                "<correction entreprise=\"{}\">\n<ecrit_par_toi>\n{}\n</ecrit_par_toi>\n<envoye_par_samuel>\n{}\n</envoye_par_samuel>\n</correction>".format(
                    escape(l.entreprise), _texte_brouillon(l), _texte_final(l))
                for l in corr))
    return DEMANDE.format(
        ref=' ref="{}"'.format(escape(lettre.offre_ref)) if lettre.offre_ref else "",
        offre=lettre.offre.strip() or "(pas de texte d'offre)",
        priorites=lettre.priorites.strip() or "(aucune)",
        lecons=bloc_lecons, corrections=bloc_corr)


# --------------------------------------------------------------------------
# L'appel à Claude


PAS_DE_MOTEUR = (
    "Claude n'est pas relié : avec ton abonnement, crée un jeton par "
    "`claude setup-token` et mets-le dans CLAUDE_CODE_OAUTH_TOKEN ; avec "
    "l'API facturée à l'usage, renseigne ANTHROPIC_API_KEY. Dans le .env du "
    "serveur, puis redémarre Awen.")


def moteur():
    """« abonnement », « api », ou None si rien n'est relié."""
    cfg = current_app.config
    choix = (cfg.get("LETTRE_MOTEUR") or "auto").strip().lower()
    if choix in ("abonnement", "api"):
        return choix
    if cfg.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return "abonnement"
    if cfg.get("ANTHROPIC_API_KEY"):
        return "api"
    return None


def _appel(system, user, schema, effort, cache=True):
    """Un appel structuré, par le moteur configuré.

    Renvoie (données JSON, {"modele", "entree", "sortie"}).
    """
    m = moteur()
    if m == "abonnement":
        return _appel_claude_code(system, user, schema, effort)
    if m == "api":
        return _appel_api(system, user, schema, effort, cache)
    raise LettreErreur(PAS_DE_MOTEUR)


def _explique(texte):
    """Un échec de Claude Code, dit en français et avec le geste qui répare."""
    bas = (texte or "").lower()
    if any(m in bas for m in ("usage limit", "limit reached", "quota", "rate limit")):
        return ("Ton abonnement Claude a atteint sa limite d'utilisation pour "
                "l'instant : réessaie quand elle sera réinitialisée.")
    if any(m in bas for m in ("oauth", "401", "authentication", "unauthorized",
                              "/login", "not logged in", "invalid api key",
                              "credential")):
        return ("Le jeton Claude Code est refusé ou expiré : refais "
                "`claude setup-token` sur ton PC et remplace "
                "CLAUDE_CODE_OAUTH_TOKEN dans le .env du serveur.")
    extrait = " ".join((texte or "").split())[:240]
    return "Claude Code a échoué : {}".format(extrait or "aucun message")


def _appel_claude_code(system, user, schema, effort="medium"):
    """Claude Code sans interface, avec l'abonnement de Samuel.

    - Aucun outil : il n'a qu'à écrire, tout est dans le message système.
    - Rien de la configuration du compte : ni connecteurs claude.ai, ni
      skills, ni réglages. Les définitions d'outils des connecteurs (Canva,
      Drive…) pesaient à elles seules 50 000 jetons par lettre.
    - La réflexion plafonne à LETTRE_EFFORT_ABONNEMENT (medium) : c'est
      elle qui consomme le plus, et une lettre n'a pas besoin du maximum.
    - La sortie suit le schéma JSON (--json-schema), comme avec l'API.
    - Les variables ANTHROPIC_* sont retirées de son environnement : avec
      une clé d'API sous la main, Claude Code la facturerait au lieu
      d'utiliser l'abonnement.
    - Il tourne dans un dossier vide : aucun CLAUDE.md ni réglage de projet
      ne s'invite dans la lettre.
    Sans jeton, il se sert de la connexion déjà faite sur la machine (le PC).
    """
    cfg = current_app.config
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC_")}
    env["DISABLE_AUTOUPDATER"] = "1"
    if cfg.get("CLAUDE_CODE_OAUTH_TOKEN"):
        env["CLAUDE_CODE_OAUTH_TOKEN"] = cfg["CLAUDE_CODE_OAUTH_TOKEN"]
    plafond = (cfg.get("LETTRE_EFFORT_ABONNEMENT") or "medium").lower()
    if effort not in EFFORTS:
        effort = "medium"
    if plafond in EFFORTS and EFFORTS.index(effort) > EFFORTS.index(plafond):
        effort = plafond
    cmd = [cfg.get("CLAUDE_BIN") or "claude", "-p", "--output-format", "json",
           "--json-schema", json.dumps(schema, ensure_ascii=False),
           "--tools", "", "--no-session-persistence", "--effort", effort,
           "--strict-mcp-config", "--disable-slash-commands",
           "--setting-sources", ""]
    if cfg.get("LETTRE_MODEL_ABONNEMENT"):
        cmd += ["--model", cfg["LETTRE_MODEL_ABONNEMENT"]]
    with tempfile.TemporaryDirectory(prefix="awen-lettre-") as dossier:
        fichier = Path(dossier) / "systeme.md"
        fichier.write_text(system, encoding="utf-8")
        cmd += ["--system-prompt-file", str(fichier)]
        try:
            r = subprocess.run(cmd, input=user, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", cwd=dossier,
                               env=env, timeout=DELAI_CLAUDE_CODE)
        except FileNotFoundError:
            raise LettreErreur("Claude Code n'est pas installé ici : l'image "
                               "d'Awen l'installe, reconstruis-la "
                               "(docker compose up -d --build).")
        except subprocess.TimeoutExpired:
            raise LettreErreur("Claude Code n'a pas répondu en dix minutes : "
                               "réessaie.")
    try:
        sortie = json.loads(r.stdout)
    except ValueError:
        raise LettreErreur(_explique(r.stderr or r.stdout))
    if sortie.get("is_error") or sortie.get("subtype") != "success":
        raise LettreErreur(_explique("{} {}".format(sortie.get("result") or "",
                                                     r.stderr or "")))
    data = sortie.get("structured_output")
    if not isinstance(data, dict):
        try:
            data = json.loads(sortie.get("result") or "")
        except ValueError:
            raise LettreErreur("Réponse illisible de Claude Code : réessaie.")
    usage = sortie.get("usage") or {}
    # Claude Code confie aussi de petites tâches à un modèle léger : celui
    # qui a écrit la lettre est celui qui a produit le plus de texte.
    par_modele = sortie.get("modelUsage") or {}

    def ecrit(modele):
        u = par_modele[modele]
        return (u.get("outputTokens") or 0) if isinstance(u, dict) else 0

    return data, {
        "modele": max(par_modele, key=ecrit) if par_modele else "claude-code",
        "entree": sum(usage.get(k) or 0 for k in (
            "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")),
        "sortie": usage.get("output_tokens") or 0,
    }


def _client():
    import anthropic
    cle = current_app.config.get("ANTHROPIC_API_KEY")
    if not cle:
        raise LettreErreur(
            "Pas de clé d'API Claude : ajoute ANTHROPIC_API_KEY dans le .env "
            "du serveur, puis redémarre Awen.")
    # Le délai couvre une lettre écrite à effort élevé ; la génération tourne
    # en arrière-plan, aucune requête web n'attend après elle.
    return anthropic.Anthropic(api_key=cle, timeout=300.0, max_retries=2)


def _appel_api(system, user, schema, effort, cache=True):
    """L'API Claude, facturée à l'usage."""
    import anthropic
    client = _client()
    systeme = [{"type": "text", "text": system}]
    if cache:
        systeme[0]["cache_control"] = {"type": "ephemeral"}
    modele = current_app.config.get("LETTRE_MODEL") or MODELE
    try:
        msg = client.beta.messages.create(
            model=modele,
            max_tokens=16000,
            betas=BETAS,
            fallbacks="default",
            system=systeme,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort,
                           "format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.AuthenticationError:
        raise LettreErreur("La clé d'API Claude est refusée : vérifie "
                           "ANTHROPIC_API_KEY dans le .env du serveur.")
    except anthropic.PermissionDeniedError as e:
        raise LettreErreur("Accès refusé par l'API Claude : {}".format(e.message))
    except anthropic.RateLimitError:
        raise LettreErreur("Trop de demandes envoyées à Claude : réessaie "
                           "dans une minute.")
    except anthropic.BadRequestError as e:
        raise LettreErreur("Requête refusée par l'API Claude : {}".format(e.message))
    except anthropic.APIStatusError as e:
        raise LettreErreur("L'API Claude a répondu une erreur {} : {}".format(
            e.status_code, e.message))
    except anthropic.APIConnectionError:
        raise LettreErreur("Claude ne répond pas : le serveur n'arrive pas à "
                           "joindre l'API. Réessaie dans un instant.")

    if msg.stop_reason == "refusal":
        raise LettreErreur("Claude a refusé d'écrire ce texte.")
    if msg.stop_reason == "max_tokens":
        raise LettreErreur("La réponse de Claude a été coupée avant la fin : "
                           "réessaie.")
    texte = next((b.text for b in msg.content if b.type == "text"), "")
    try:
        data = json.loads(texte)
    except ValueError:
        raise LettreErreur("Réponse illisible de Claude : réessaie.")
    u = msg.usage
    return data, {
        "modele": msg.model,
        "entree": ((u.input_tokens or 0)
                   + (getattr(u, "cache_read_input_tokens", 0) or 0)
                   + (getattr(u, "cache_creation_input_tokens", 0) or 0)),
        "sortie": u.output_tokens or 0,
    }


def generer(lettre_id):
    """Écrit la lettre. Tourne en arrière-plan ; l'état dit où on en est."""
    lettre = db.session.get(CoverLetter, lettre_id)
    if lettre is None:
        return
    try:
        src = sources()
        if src["manquants"]:
            raise LettreErreur(
                "Il manque sur le serveur : {}. Relance la synchronisation "
                "(scripts/sync-jobs.ps1) depuis le PC.".format(
                    ", ".join(src["manquants"])))
        data, meta = _appel(_systeme(src), _demande(lettre), SCHEMA_LETTRE,
                            current_app.config.get("LETTRE_EFFORT") or EFFORT)
    except LettreErreur as e:
        lettre.etat, lettre.erreur = "erreur", str(e)
        db.session.commit()
        return
    except Exception as e:                      # jamais une lettre bloquée
        current_app.logger.exception("lettre %s", lettre_id)
        lettre.etat = "erreur"
        lettre.erreur = "Erreur inattendue : {}".format(e)
        db.session.commit()
        return

    paragraphes = [_net(p) for p in data.get("paragraphes", []) if p.strip()]
    lettre.entreprise = _net(data.get("entreprise", "")) or lettre.entreprise
    lettre.poste = _net(data.get("poste", "")) or lettre.poste
    lettre.destinataire = "\n".join(_net(l) for l in data.get("destinataire", [])
                                    if l.strip())
    lettre.objet = _net(data.get("objet", ""))
    lettre.salutation = _net(data.get("salutation", "")) or "Madame, Monsieur,"
    lettre.corps = "\n\n".join(paragraphes)
    lettre.notes = data.get("notes", "").strip()
    lettre.brouillon = json.dumps({
        "destinataire": lettre.destinataire, "objet": lettre.objet,
        "salutation": lettre.salutation, "corps": lettre.corps},
        ensure_ascii=False)
    lettre.modele = (meta["modele"] or "")[:40]
    lettre.jetons_entree = meta["entree"]
    lettre.jetons_sortie = meta["sortie"]
    lettre.etat, lettre.erreur = "prete", ""
    db.session.commit()


# --------------------------------------------------------------------------
# Apprendre des corrections


LECONS = """Tu aides un assistant d'écriture à progresser. On te donne une lettre de motivation telle que l'assistant l'a écrite, puis telle que Samuel l'a corrigée avant de l'envoyer. Déduis-en au plus trois règles que l'assistant appliquera aux lettres suivantes.

- Une règle vaut pour d'autres lettres : jamais un fait propre à cette entreprise ou à ce poste.
- Une phrase à l'impératif, en français, 30 mots au plus, sans tiret long.
- Ne reprends pas une règle déjà connue, même reformulée.
- Ne déduis rien de corrections mineures : une coquille, une date, un nom propre, une tournure isolée. Dans ce cas, renvoie une liste vide."""


def _texte_brouillon(lettre):
    try:
        b = json.loads(lettre.brouillon or "{}")
    except ValueError:
        return ""
    if not b:
        return ""
    return "\n\n".join(x for x in (b.get("destinataire", ""), "Objet : " + b.get("objet", ""),
                                   b.get("salutation", ""), b.get("corps", "")) if x)


def _texte_final(lettre):
    return "\n\n".join(x for x in (lettre.destinataire, "Objet : " + lettre.objet,
                                   lettre.salutation, lettre.corps) if x)


def _ressemblance(a, b):
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _empreinte(texte):
    return hashlib.sha1(texte.encode("utf-8")).hexdigest()


def a_etudier(lettre):
    """Vrai si la version exportée diffère assez du brouillon pour apprendre."""
    avant, apres = _texte_brouillon(lettre), _texte_final(lettre)
    if not avant or lettre.lecons_pour == _empreinte(apres):
        return False
    return _ressemblance(avant, apres) < SEUIL_LECON


def etudier(lettre_id):
    """Tire des règles de la correction. Tourne en arrière-plan, sans bruit :
    une analyse ratée ne doit jamais gêner l'export d'une lettre."""
    lettre = db.session.get(CoverLetter, lettre_id)
    if lettre is None or not a_etudier(lettre):
        return
    apres = _texte_final(lettre)
    connues = "\n".join("- " + l.texte for l in _lecons_actives()) or "(aucune)"
    demande = ("<regles_deja_connues>\n{}\n</regles_deja_connues>\n\n"
               "<ecrite_par_l_assistant>\n{}\n</ecrite_par_l_assistant>\n\n"
               "<corrigee_par_samuel>\n{}\n</corrigee_par_samuel>").format(
                   connues, _texte_brouillon(lettre), apres)
    try:
        data, _meta = _appel(LECONS, demande, SCHEMA_LECONS, "medium",
                             cache=False)
    except Exception as e:
        current_app.logger.warning("leçons de la lettre %s : %s", lettre_id, e)
        return
    for texte in data.get("lecons", [])[:3]:
        texte = _net(texte)[:400]
        if texte:
            db.session.add(LetterLesson(texte=texte, lettre_id=lettre.id))
    lettre.lecons_pour = _empreinte(apres)
    db.session.commit()


def abandonnee(lettre):
    """Un redémarrage du serveur (un déploiement, par exemple) tue le fil qui
    écrivait la lettre. Sans ce garde-fou, elle resterait « en cours » pour
    toujours et la page attendrait sans fin. Vrai si la lettre vient d'être
    passée en erreur."""
    if (lettre.etat != "generation" or lettre.updated_at is None
            or datetime.now() - lettre.updated_at < ABANDON):
        return False
    lettre.etat = "erreur"
    lettre.erreur = ("La génération s'est interrompue, sans doute un "
                     "redémarrage du serveur : relance-la.")
    db.session.commit()
    return True


def lancer(fonction, lettre_id):
    """Exécute `fonction(lettre_id)` dans un fil, avec le contexte de l'app."""
    app = current_app._get_current_object()

    def tache():
        with app.app_context():
            try:
                fonction(lettre_id)
            finally:
                db.session.remove()

    threading.Thread(target=tache, daemon=True).start()


# --------------------------------------------------------------------------
# Le texte


_SIGNES = {"—": ", ", "–": "-", " ": " ", " ": " "}


def _net(s):
    """Retire les tirets longs que Claude laisserait passer malgré la consigne."""
    s = (s or "").strip()
    s = re.sub(r"\s*—\s*", ", ", s)
    for a, b in _SIGNES.items():
        s = s.replace(a, b)
    return s


def mots(lettre):
    return len(re.findall(r"\w+", " ".join((lettre.objet, lettre.salutation,
                                            lettre.corps))))


# --------------------------------------------------------------------------
# Le PDF
#
# La mise en page reprend celle de ses lettres Word : A4, marges de 2,54 cm,
# nom en gras en 12, le reste en 11, date à droite, objet en gras, corps
# justifié en interligne 1,5, signature en gras. Helvetica, qui a les
# mêmes chasses qu'Arial : les lignes cassent aux mêmes endroits.


def _winansi(s):
    """Helvetica ne connaît que l'encodage WinAnsi : on ramène le reste à
    sa lettre de base plutôt que de laisser un carré dans une candidature."""
    out = []
    for ch in s:
        try:
            ch.encode("cp1252")
            out.append(ch)
        except UnicodeEncodeError:
            base = unicodedata.normalize("NFKD", ch)[:1]
            try:
                base.encode("cp1252")
                out.append(base if base.strip() else " ")
            except UnicodeEncodeError:
                out.append(" ")
    return "".join(out)


def _p(texte):
    return escape(_winansi(texte)).replace("\n", "<br/>")


def nom_fichier(lettre):
    nom = re.sub(r'[\\/:*?"<>|]+', " ", lettre.entreprise or "Candidature")
    return "{} - Lettre de motivation.pdf".format(" ".join(nom.split()))


def nom_markdown(lettre):
    """« Yavin - Product Owner Core.md », comme les lettres du dossier."""
    titre = " - ".join(x for x in (lettre.entreprise, lettre.poste) if x) or "Candidature"
    return "{}.md".format(" ".join(re.sub(r'[\\/:*?"<>|]+', " ", titre).split()))


def markdown(lettre, jour=None):
    """La lettre au format des lettres du dossier « Lettres de motivation » :
    un titre, la date, une ligne « --- », puis la lettre telle qu'envoyée.
    Pour la ranger dans le projet Recherche de CDI à côté des autres."""
    jour = jour or date.today()
    exp = [l for l in lettre.expediteur.splitlines() if l.strip()]
    titre = ", ".join(x for x in (lettre.entreprise, lettre.poste) if x) or "Candidature"
    blocs = ["# {}".format(titre),
             "- Date : {:%d/%m/%Y}\n- Écrite avec Awen".format(jour),
             "---",
             "\n".join(exp),
             lettre.date_ligne,
             lettre.destinataire.strip(),
             "Objet : {}".format(lettre.objet),
             lettre.salutation or "Madame, Monsieur,",
             lettre.corps.strip(),
             exp[0] if exp else ""]
    return "\n\n".join(b for b in blocs if b) + "\n"


def _histoire(lettre, interligne, apres):
    from reportlab.lib.enums import TA_JUSTIFY, TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph

    base = ParagraphStyle("base", fontName="Helvetica", fontSize=11,
                          leading=12.65)
    gras = ParagraphStyle("gras", parent=base, fontName="Helvetica-Bold")
    nom = ParagraphStyle("nom", parent=gras, fontSize=12, leading=14)
    droite = ParagraphStyle("droite", parent=base, alignment=TA_RIGHT,
                            spaceAfter=8)
    corps = ParagraphStyle("corps", parent=base, alignment=TA_JUSTIFY,
                           leading=interligne, spaceAfter=apres)
    signature = ParagraphStyle("signature", parent=gras, spaceBefore=20)

    exp = [l for l in lettre.expediteur.splitlines() if l.strip()]
    story = []
    for i, l in enumerate(exp):
        style = nom if i == 0 else base
        if i == len(exp) - 1:
            style = ParagraphStyle("exp_fin", parent=style, spaceAfter=10)
        story.append(Paragraph(_p(l), style))
    story.append(Paragraph(_p(lettre.date_ligne or date_du_jour()), droite))
    dest = [l for l in lettre.destinataire.splitlines() if l.strip()]
    for i, l in enumerate(dest):
        story.append(Paragraph(_p(l), ParagraphStyle(
            "dest", parent=base, spaceAfter=10 if i == len(dest) - 1 else 0)))
    story.append(Paragraph(_p("Objet : " + lettre.objet),
                           ParagraphStyle("objet", parent=gras, spaceAfter=12)))
    story.append(Paragraph(_p(lettre.salutation or "Madame, Monsieur,"),
                           ParagraphStyle("salut", parent=base, spaceAfter=10)))
    for para in re.split(r"\n\s*\n", lettre.corps.strip()):
        if para.strip():
            story.append(Paragraph(_p(" ".join(para.split())), corps))
    if exp:
        story.append(Paragraph(_p(exp[0]), signature))
    return story


def _anonyme(data):
    """Ce que reportlab écrit quoi qu'on lui dise : son nom dans deux
    commentaires (l'en-tête et la fin du fichier) et un dictionnaire
    d'informations daté. On les remplace par des espaces de même longueur :
    les positions de la table xref restent justes, et le fichier ne dit plus
    rien de l'outil ni de la date.

    Un flux de page est encodé en ASCII85, qui n'écrit jamais d'espace :
    « ReportLab » précédé d'un espace ne peut venir que d'un commentaire."""
    def blanc(m):
        return m.group(1) + b" " * (len(m.group(0)) - len(m.group(1)))
    data = re.sub(rb"(?m)^(%[^\n ]*) ReportLab [^\n]*", blanc, data)
    data = re.sub(rb"(<<)[^<>]*/CreationDate[^<>]*(?=>>)", blanc, data)
    return data


def pdf(lettre):
    """Le PDF de la lettre, sur une page. Lève LettreTropLongue sinon.

    Trois essais, du plus aéré au plus serré, avant de renoncer : on resserre
    l'interligne plutôt que de couper un mot de Samuel.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate

    marge = 72                                  # 2,54 cm, comme dans Word
    for interligne, apres in ((19, 8), (17, 6), (15.5, 5)):
        buf = BytesIO()
        pages = []
        doc = SimpleDocTemplate(
            buf, pagesize=A4, leftMargin=marge, rightMargin=marge,
            topMargin=marge, bottomMargin=marge,
            # « Une page, sans aucune métadonnée » : rien qui dise l'outil,
            # l'auteur ou la date de fabrication.
            title="", author="", subject="", creator="", producer="",
            keywords="", invariant=1)
        doc.build(_histoire(lettre, interligne, apres),
                  onFirstPage=lambda c, d: pages.append(1),
                  onLaterPages=lambda c, d: pages.append(1))
        if len(pages) == 1:
            return _anonyme(buf.getvalue())

    # Combien de lignes dépassent, au réglage le plus serré.
    largeur = A4[0] - 2 * marge
    hauteur = A4[1] - 2 * marge
    total = 0
    for f in _histoire(lettre, 15.5, 5):
        _w, h = f.wrap(largeur, hauteur)
        total += h + f.getSpaceBefore() + f.getSpaceAfter()
    raise LettreTropLongue(max(1, int((total - hauteur) // 15.5) + 1))
