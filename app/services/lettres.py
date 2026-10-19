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
"""
import difflib
import hashlib
import html
import json
import re
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
CV = "_CV ATS (source modifiable).html"
INSTRUCTIONS = "_Instructions veille PO (tache quotidienne).md"
DOSSIER = "Lettres de motivation"
GABARIT = "_Modele de lettre (template).md"

EXEMPLES = 3            # lettres envoyées montrées pour le ton
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


def _exemples():
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
    out = []
    for f in fichiers[:EXEMPLES]:
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


SYSTEME = """Tu écris les lettres de motivation de Samuel Scalbert, en français, pour des candidatures en CDI. Ses règles, son modèle, sa fiche profil, son CV et les lettres qu'il a déjà envoyées sont ci-dessous : c'est ta seule source sur lui.

<regles>
{regles}
</regles>

Ce qui s'ajoute à ces règles :
- Aucun fait, outil, chiffre ou expérience absent de la fiche profil et du CV. Ce que l'offre demande et qu'il n'a pas, c'est la friction : nomme-la et dis comment il la comble, sans la nier.
- Respecte la section « Les formulations à corriger » de la fiche profil.
- Une page A4 au plus : 280 à 340 mots en tout, formule de politesse comprise.
- Ni tiret long ni tiret moyen : une virgule, deux-points ou des parenthèses à la place.
- Pas d'adjectif flatteur sans preuve (« passionné », « dynamique », « rigoureux ») : un fait vaut mieux.
- Le ton suit les lettres envoyées : direct, concret, à la première personne.

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
</lettres_envoyees>

Ta réponse remplit le schéma JSON demandé :
- entreprise, poste : tels qu'ils doivent apparaître dans le nom du fichier.
- destinataire : 1 à 3 lignes, comme dans les lettres envoyées (« À l'attention de… », l'entreprise, la ville si l'offre la donne).
- objet : le texte après « Objet : », avec la référence de l'offre si elle en a une.
- salutation : « Madame, Monsieur, » sauf si l'offre nomme la personne.
- paragraphes : le corps puis la formule de politesse, un paragraphe par élément. Sans la signature.
- notes : pour Samuel, trois à cinq lignes courtes : l'élément concret de l'entreprise retenu et d'où il vient, l'histoire choisie, la friction traitée, et ce qu'il doit vérifier avant d'envoyer."""

DEMANDE = """<offre{ref}>
{offre}
</offre>

<priorites_de_samuel>
{priorites}
</priorites_de_samuel>
{lecons}{corrections}
Écris la lettre pour cette offre. Les priorités de Samuel passent avant tes propres choix : chacune doit se retrouver explicitement dans la lettre. Si l'offre ne donne aucun élément concret sur l'entreprise, prends le plus précis qu'elle contienne et signale-le dans les notes."""


def _systeme(src):
    exemples = "\n\n".join(
        '<lettre titre="{}">\n{}\n</lettre>'.format(escape(t), c)
        for t, c in src["exemples"]) or "(aucune)"
    return SYSTEME.format(regles=src["regles"], gabarit=src["gabarit"],
                          profil=src["profil"], cv=src["cv"],
                          exemples=exemples)


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


def _appel(system, user, schema, effort, cache=True):
    """Un appel structuré : renvoie (données JSON, message)."""
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
        return json.loads(texte), msg
    except ValueError:
        raise LettreErreur("Réponse illisible de Claude : réessaie.")


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
        data, msg = _appel(_systeme(src), _demande(lettre), SCHEMA_LETTRE,
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
    lettre.modele = msg.model
    usage = msg.usage
    lettre.jetons_entree = ((usage.input_tokens or 0)
                            + (getattr(usage, "cache_read_input_tokens", 0) or 0)
                            + (getattr(usage, "cache_creation_input_tokens", 0) or 0))
    lettre.jetons_sortie = usage.output_tokens or 0
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
        data, _msg = _appel(LECONS, demande, SCHEMA_LECONS, "medium",
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
