"""Rattraper une offre que la veille a écartée à tort.

POURQUOI

La veille lit vite, et parfois mal. Le 10/11/2026, elle a écarté « Product
Owner / Business Analyst Finance, INOCO » pour « plus de 5 ans exigés » :
elle avait lu l'en-tête de Welcome to the Jungle (« Expérience : > 5 ans »,
une case cochée dans une liste), pas l'annonce, qui dit « > 3-5 ans ». Une
offre faite pour Samuel a disparu dans la liste des écartées.

Rattraper, c'est un geste sur la page Jobs : l'offre remonte parmi celles à
postuler, avec son annonce lue sur sa page, et le formulaire de lettre la
propose comme les autres.

L'ERREUR REPART VERS LA VEILLE

Awen écrit les offres rattrapées dans data/offres-rattrapees.md, et
scripts/sync-jobs.ps1 rapatrie ce fichier dans le dossier « Recherche de CDI »
du PC, le seul que lit la veille. Ses consignes lui font lire ce fichier :
chaque ligne est une erreur de jugement à ne pas refaire.
"""
import csv
import html
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import requests
from flask import current_app

from ..models import OffreRattrapee, db

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
TIMEOUT = 15
TEXTE_MAX = 8000
REGISTRE = "Offres vues.csv"
FICHIER = "offres-rattrapees.md"


# --------------------------------------------------------------------------
# Les lignes du compte rendu


def analyse_ligne(ligne):
    """« Intitulé, Entreprise (détails) : motif » -> ses trois parties.

    L'intitulé peut contenir des virgules (« Product Owner, Conduite du
    changement, Thales ») : l'entreprise est ce qui suit la DERNIÈRE virgule.
    Les détails entre parenthèses (lieu, salaire, date) ne font partie ni de
    l'un ni de l'autre.
    """
    texte = re.sub(r"\s+", " ", ligne).strip().lstrip("-* ").strip()
    gauche, _, motif = texte.partition(" : ")
    gauche = re.sub(r"\*\*", "", gauche)
    gauche = re.sub(r"\s*\([^()]*\)\s*$", "", gauche).strip()
    intitule, sep, entreprise = gauche.rpartition(", ")
    if not sep:
        intitule, entreprise = gauche, ""
    return {"ligne": texte, "intitule": intitule.strip(),
            "entreprise": entreprise.strip(), "motif": motif.strip()}


def blocs_ecartees(texte):
    """La section des écartées, en blocs : du texte, ou une liste d'offres.

    Chaque puce devient une offre qu'on peut rattraper ; le reste (titres de
    niveau 3, paragraphe des déjà vues) reste du texte, affiché tel quel.
    """
    blocs, courant, puce = [], [], None

    def fermer_texte():
        if courant and "\n".join(courant).strip():
            blocs.append({"kind": "md", "text": "\n".join(courant).strip()})
        courant.clear()

    for ligne in (texte or "").splitlines():
        if re.match(r"^[-*]\s+", ligne):
            fermer_texte()
            if not blocs or blocs[-1]["kind"] != "liste":
                blocs.append({"kind": "liste", "offres": []})
            puce = analyse_ligne(ligne)
            blocs[-1]["offres"].append(puce)
        elif puce is not None and ligne.startswith((" ", "\t")) and ligne.strip():
            puce["ligne"] += " " + ligne.strip()      # suite de la puce
            puce.update({k: v for k, v in analyse_ligne(puce["ligne"]).items()
                         if k != "ligne"})
        else:
            puce = None
            courant.append(ligne)
    fermer_texte()
    return blocs


# --------------------------------------------------------------------------
# Le lien, dans le registre de la veille


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"\b[fh]\s*/\s*[fh]\b|\(?\b[hf]/[fh]\)?", " ", s.lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def registre_lien(entreprise, intitule):
    """Le lien de l'offre dans « Offres vues.csv », ou "".

    Même entreprise, et l'intitulé le plus proche ; la dernière vue l'emporte
    à égalité. La veille y note un lien par offre ouverte, alors que la ligne
    du compte rendu n'en porte pas.
    """
    base = current_app.config.get("JOB_SEARCH_DIR")
    if not base:
        return ""
    chemin = Path(base) / REGISTRE
    if not chemin.exists():
        return ""
    cible_e, cible_i = _norm(entreprise), _norm(intitule)
    meilleur, score = "", 0.0
    with open(chemin, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if _norm(r.get("entreprise")) != cible_e or not (r.get("lien") or "").strip():
                continue
            s = SequenceMatcher(None, _norm(r.get("intitule")), cible_i).ratio()
            if s >= score:
                meilleur, score = r["lien"].split()[0], s
    return meilleur if score >= 0.6 else ""


# --------------------------------------------------------------------------
# L'annonce, lue sur sa page


def _propre(texte):
    t = re.sub(r"<br\s*/?>|</(p|li|h[1-6]|div|ul|ol)>", "\n", texte)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return "\n".join(re.sub(r"[ \t\xa0]+", " ", l).strip()
                     for l in t.splitlines() if l.strip())


def _jobposting(page):
    """Le bloc JSON-LD JobPosting, celui que lit Google Jobs. {} sinon."""
    for bloc in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>',
                           page, flags=re.S):
        try:
            data = json.loads(bloc)
        except ValueError:
            continue
        for x in data if isinstance(data, list) else data.get("@graph", [data]):
            if isinstance(x, dict) and x.get("@type") == "JobPosting":
                return x
    return {}


def extraire(page, url=""):
    """Le texte de l'annonce : son en-tête, puis le texte visible de la page
    à partir de la description.

    Le JSON-LD seul ne suffit pas : chez Welcome to the Jungle, il donne les
    missions mais pas « Ce que l'on cherche », là où se lit l'expérience
    demandée. On s'en sert pour savoir où commence l'annonce dans le texte
    visible, et on garde la suite.
    """
    ld = _jobposting(page)
    visible = _propre(re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ",
                             page, flags=re.S))
    description = _propre(ld.get("description", ""))
    if description:
        # Le texte visible à partir de la description ; à défaut (page rendue
        # en JavaScript, description absente du HTML), la description seule.
        i = visible.find(description.splitlines()[0][:50])
        corps = visible[i:i + TEXTE_MAX].strip() if i >= 0 else ""
        if len(corps) < len(description):
            corps = description[:TEXTE_MAX]
    else:
        debut = visible.find(ld["title"]) if ld.get("title") else -1
        corps = visible[max(debut, 0):][:TEXTE_MAX].strip()
    org = (ld.get("hiringOrganization") or {})
    entete = [
        "Intitulé : " + ld["title"] if ld.get("title") else "",
        "Entreprise : " + org.get("name", "") if isinstance(org, dict) and org.get("name") else "",
        "Publiée le : " + str(ld.get("datePosted", ""))[:10] if ld.get("datePosted") else "",
        "Lien : " + url if url else "",
    ]
    return ("\n".join(x for x in entete if x) + "\n\n" + corps).strip()


def texte_offre(url):
    r = requests.get(url, timeout=TIMEOUT, headers={
        "User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9"})
    r.raise_for_status()
    return extraire(r.text, url)


# --------------------------------------------------------------------------
# Le geste


def rattraper(rapport, ligne):
    """Rattrape l'offre de cette ligne du compte rendu `rapport`.

    Rattraper deux fois la même offre ne la duplique pas. Un lien ou une
    annonce introuvables ne bloquent rien : la lettre se demande alors avec
    l'annonce collée à la main.
    """
    p = analyse_ligne(ligne)
    deja = OffreRattrapee.query.filter_by(
        rapport=rapport, entreprise=p["entreprise"], intitule=p["intitule"]).first()
    if deja is not None:
        return deja
    o = OffreRattrapee(rapport=rapport, entreprise=p["entreprise"],
                       intitule=p["intitule"], motif_ecart=p["motif"])
    o.url = registre_lien(p["entreprise"], p["intitule"])
    if o.url:
        try:
            o.texte = texte_offre(o.url)
        except Exception as e:                       # site fermé, délai...
            current_app.logger.warning("rattrapage %s : %s", o.url, e)
    db.session.add(o)
    db.session.commit()
    exporter()
    return o


def annuler(o):
    db.session.delete(o)
    db.session.commit()
    exporter()


def ref(o):
    """La référence d'une offre rattrapée dans le formulaire de lettre."""
    return "rattrapee:{}".format(o.id)


def texte_lettre(o):
    """Ce que le formulaire de lettre envoie à Claude pour cette offre."""
    if o.texte:
        return o.texte
    return "\n".join(x for x in (
        "Intitulé : " + o.intitule, "Entreprise : " + o.entreprise,
        "Lien : " + o.url if o.url else "") if x)


def _chemin():
    return Path(current_app.config.get("RATTRAPAGE_FICHIER") or
                Path(current_app.config["BASE_DIR"]) / "data" / FICHIER)


def exporter():
    """Écrit la liste des offres rattrapées, pour la veille."""
    lignes = [
        "# Offres rattrapées par Samuel",
        "",
        "> Écrit par Awen. Chaque ligne est une offre que la veille avait "
        "écartée et que Samuel a jugée bonne : une erreur de jugement à ne pas "
        "refaire. Ne repropose pas ces offres, elles sont déjà traitées.",
        "",
    ]
    for o in OffreRattrapee.query.order_by(OffreRattrapee.id):
        lignes.append("- {} | {} | {} | écartée pour : {} | {}".format(
            o.rapport, o.entreprise, o.intitule, o.motif_ecart or "?", o.url or "sans lien"))
    chemin = _chemin()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
