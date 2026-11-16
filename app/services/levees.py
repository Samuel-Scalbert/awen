"""Les startups qui viennent de lever, leurs dirigeants, et le mail à leur écrire.

POURQUOI

Le 12/11/2026, Stanislas Denis a donné à Samuel un signal de recrutement :
une levée de fonds. Et une méthode : écrire aux dirigeants, court, au culot,
pour obtenir un rendez-vous téléphonique. Cette page fait la liste et écrit
le brouillon ; Samuel envoie lui-même, peu de mails, chacun relu.

LA CHAÎNE, SANS CLÉ NI COMPTE

1. Les récapitulatifs hebdomadaires de Maddyness (nom, secteur, montant,
   investisseurs), lus dans le bloc HTML « financements » de l'article.
2. La fiche Maddyness de l'entreprise : siège, année de création, site,
   « Ils recrutent ».
3. L'API Recherche d'entreprises (api.gouv.fr) : SIREN, effectif, dirigeants
   inscrits au registre. Le bon résultat concorde sur la ville et l'année.
4. Le site de l'entreprise : adresses publiées, et le format des adresses
   nominatives s'il en apparaît une ; un extrait du texte, pour le mail.
5. L'adresse probable de chaque dirigeant (prenom@, puis prenom.nom@), avec
   une seule vérification : le domaine reçoit du courrier (MX). Aucune sonde
   SMTP : c'est intrusif et ça fait blacklister l'expéditeur.

Le mail est écrit par le même moteur que les lettres (lettres.py) avec le
skill .claude/skills/mail-prospection : l'abonnement Claude, l'API en secours.
"""
import html
import json
import re
import time
import unicodedata
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin, urlparse
from xml.sax.saxutils import escape

import requests
from flask import current_app

from ..models import CollecteLevees, Levee, MailProspection, db
from . import lettres
from .lettres import LettreErreur, lancer

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36",
      "Accept-Language": "fr-FR,fr;q=0.9"}
MADDY = "https://www.maddyness.com"
API_ENT = "https://recherche-entreprises.api.gouv.fr/search"
API_ADRESSE = "https://api-adresse.data.gouv.fr/search/"
DNS = "https://cloudflare-dns.com/dns-query"
IDF = ("75", "77", "78", "91", "92", "93", "94", "95")
EFFECTIF_MAX = 249
TEXTE_SITE_MAX = 2500
ABANDON = timedelta(minutes=30)

# Tranches d'effectif de l'INSEE : code -> (libellé, borne haute)
TRANCHES = {"NN": ("non renseigné", None), "00": ("0 salarié", 0), "01": ("1-2", 2),
            "02": ("3-5", 5), "03": ("6-9", 9), "11": ("10-19", 19), "12": ("20-49", 49),
            "21": ("50-99", 99), "22": ("100-199", 199), "31": ("200-249", 249),
            "32": ("250-499", 499), "41": ("500-999", 999), "42": ("1000-1999", 1999),
            "51": ("2000-4999", 4999), "52": ("5000-9999", 9999), "53": ("10000+", 10 ** 6)}
ROLES = ("président", "directeur général", "gérant", "co-gérant")
GENERIQUES = {"contact", "hello", "bonjour", "info", "infos", "hi", "team", "press", "presse",
              "support", "help", "sales", "commercial", "rgpd", "dpo", "privacy", "legal",
              "admin", "noreply", "no-reply", "partenariats", "partners", "marketing",
              "communication", "office", "accueil", "service", "facturation", "billing"}
RECRUTEMENT = {"jobs", "job", "careers", "career", "recrutement", "recrutements", "rh", "hr",
               "talent", "talents", "join", "joinus", "candidature", "candidatures", "hiring"}
PAGES = ["", "mentions-legales", "mentions-legales/", "legal", "contact", "contact/",
         "a-propos", "about", "about-us", "equipe", "team", "careers", "jobs", "recrutement"]
# Les secteurs où un dev/PO IA a le plus de chances d'être utile. Le reste
# n'est pas écarté, il passe après.
SECTEURS_PROCHES = ("it", "ia", "saas", "data", "martech", "adtech", "rh", "hrtech", "edtech",
                    "fintech", "legaltech", "proptech", "insurtech", "logiciel", "software",
                    "ecommerce", "e-commerce")

_session = requests.Session()
_session.headers.update(UA)


def get(url, params=None, timeout=15, headers=None):
    """Une page, ou None. Remplacée dans les tests."""
    try:
        r = _session.get(url, params=params, timeout=timeout, headers=headers)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    # Un serveur qui ne dit pas son jeu de caractères est lu en Latin-1 par
    # requests : « gÃ©nÃ©ration ». Le HTML d'aujourd'hui est en UTF-8.
    if "charset" not in r.headers.get("content-type", "").lower():
        r.encoding = "utf-8"
    return r


def _json(r):
    try:
        return r.json() if r else None
    except ValueError:
        return None


def texte(h):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h or ""))).strip()


def _norm(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"\b(sas|sasu|sa|sarl|group|groupe|france|technologies|technology|labs?|ai|io)\b", " ", t)
    return re.sub(r"[^a-z0-9]+", "", t)


# --------------------------------------------------------------------------
# 1. Les récapitulatifs de Maddyness


def recaps(semaines):
    apres = (date.today() - timedelta(weeks=semaines)).isoformat() + "T00:00:00"
    vus, posts = set(), []
    for q in ("levé cette semaine", "levés cette semaine", "levés en une semaine"):
        r = get(MADDY + "/wp-json/wp/v2/posts", params={
            "search": q, "after": apres, "per_page": 50, "_fields": "date,link,title"})
        for p in _json(r) or []:
            if p.get("link") and p["link"] not in vus:
                vus.add(p["link"])
                posts.append({"date": p["date"][:10], "lien": p["link"],
                              "titre": texte(p["title"]["rendered"])})
    return sorted(posts, key=lambda p: p["date"], reverse=True)


def operations(recap):
    """Les opérations d'un récapitulatif, avec ce que l'article en dit."""
    r = get(recap["lien"], timeout=20)
    if not r:
        return []
    page = r.text
    phrases = re.split(r"(?<=[.!?])\s+", texte(" ".join(
        re.findall(r"<(?:p|li)[^>]*>(.*?)</(?:p|li)>", page, re.S))))
    ops = []
    for bloc in re.split(r'<div class="financements__item">', page)[1:]:
        nom = re.search(r'class="financements__name[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', bloc, re.S)
        if not nom:
            continue
        entreprise = texte(nom.group(2))
        montant = re.search(r'financements__amount">\s*([\d.,]+)\s*(M€|k€|Md€|€)?', bloc)
        contexte = [p for p in phrases if entreprise.lower() in p.lower() and len(p) < 400]
        ops.append({
            "semaine": recap["date"],
            "entreprise": entreprise,
            "fiche_maddyness": nom.group(1),
            "secteur": " ".join(texte(x) for x in re.findall(
                r'financements__hashtag">\s*<span>#?([^<]+)</span>', bloc)),
            "montant": (montant.group(1).replace(",", ".") + " " + (montant.group(2) or "")).strip()
            if montant else "",
            "investisseurs": ", ".join(texte(x).strip(" ,") for x in re.findall(
                r'base-fonds-investissements/[^"]*"[^>]*>(.*?)</a>', bloc, re.S)),
            "contexte": " ".join(contexte[:3])[:600],
        })
    return ops


def fiche(op):
    r = get(op["fiche_maddyness"])
    if not r:
        return
    t = texte(re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", r.text, flags=re.S))
    m = re.search(r"Siège social\s+(.+?)\s+Créé en\s+(\d{4})", t)
    if m:
        op["ville"], op["creee"] = m.group(1).strip(), m.group(2)
    op["recrute"] = "Ils recrutent" in t
    exclus = ("maddyness", "maddyfactory", "fundtruck", "youtube", "bcorporation", "google",
              "facebook", "twitter", "linkedin", "instagram", "x.com", "apple.com", "tiktok")
    for lien in re.findall(r'href="(https?://[^"]+)"', r.text):
        if not any(x in lien for x in exclus):
            op["site"] = lien
            break
    op["departement"] = departement(op.get("ville"))


_DEPS = {}


def departement(ville):
    """Le département d'une commune, par la Base adresse nationale : son
    « context » commence par le numéro, « 94, Val-de-Marne »."""
    if not ville:
        return ""
    if ville not in _DEPS:
        d = _json(get(API_ADRESSE, params={"q": ville, "type": "municipality", "limit": 1})) or {}
        f = (d.get("features") or [{}])[0]
        _DEPS[ville] = ((f.get("properties") or {}).get("context") or "").split(",")[0].strip()
    return _DEPS[ville]


# --------------------------------------------------------------------------
# 2. Le registre


def _cherche(q, **filtres):
    d = _json(get(API_ENT, params={"q": q, "per_page": 10, "etat_administratif": "A", **filtres}))
    time.sleep(0.2)                                   # 7 requêtes par seconde au plus
    return (d or {}).get("results") or []


def registre(op):
    """SIREN, effectif et dirigeants. La marque n'est pas toujours la raison
    sociale (« Heal.dev », « Gama Space ») : on essaie le nom, le nom sans
    ponctuation, puis la racine du domaine, filtrés sur le département."""
    variantes = [op["entreprise"], re.sub(r"[.\-_]", " ", op["entreprise"])]
    if op.get("site"):
        variantes.append(urlparse(op["site"]).netloc.lower().removeprefix("www.").split(".")[0])
    resultats, vus = [], set()
    for q in dict.fromkeys(v for v in variantes if v.strip()):
        filtres = {"departement": op["departement"]} if op.get("departement") else {}
        for e in _cherche(q, **filtres) + (_cherche(q) if filtres else []):
            if e.get("siren") not in vus:
                vus.add(e.get("siren"))
                resultats.append(e)
        if any(_norm(op["entreprise"]) == _norm(e.get("nom_complet")) for e in resultats):
            break
    meilleur, score = None, 0.0
    cible = _norm(op["entreprise"])
    for e in resultats:
        siege = e.get("siege") or {}
        noms = [e.get("nom_complet"), e.get("nom_raison_sociale"), e.get("sigle")]
        noms += siege.get("liste_enseignes") or []
        noms = [n for n in noms if n]
        sim = max((SequenceMatcher(None, cible, _norm(n)).ratio() for n in noms), default=0)
        if op.get("ville") and _norm(op["ville"]) and _norm(op["ville"]) in _norm(siege.get("libelle_commune", "")):
            sim += 0.25
        if op.get("creee") and (e.get("date_creation") or "")[:4] == op["creee"]:
            sim += 0.25
        if sim > score:
            meilleur, score = e, sim
    if not meilleur or score < 0.8:
        op["registre"] = "introuvable" if not meilleur else "douteux ({})".format(meilleur.get("nom_complet"))
        return
    e, siege = meilleur, meilleur.get("siege") or {}
    tranche = e.get("tranche_effectif_salarie") or "NN"
    op.update({
        "registre": "ok" if score >= 1.0 else "probable",
        "siren": e.get("siren", ""),
        "raison_sociale": e.get("nom_complet", ""),
        "naf": e.get("activite_principale", ""),
        "effectif": TRANCHES.get(tranche, (tranche, None))[0],
        "effectif_max": TRANCHES.get(tranche, (tranche, None))[1],
        "dirigeants": sorted([
            {"prenom": (d.get("prenoms") or "").split()[0].title() if d.get("prenoms") else "",
             "nom": re.sub(r"\s*\(.*?\)", "", d.get("nom") or "").title(),
             "qualite": d.get("qualite") or "", "adresses": []}
            for d in e.get("dirigeants") or []
            if d.get("type_dirigeant") == "personne physique"
            and (d.get("qualite") or "").lower().startswith(ROLES)],
            key=lambda d: 0 if d["qualite"].lower().startswith("président") else 1),
    })
    if not op.get("departement") and siege.get("code_postal"):
        op["departement"] = siege["code_postal"][:2]


# --------------------------------------------------------------------------
# 3. Le site : adresses publiées, extrait du texte


def decode_cf(hexa):
    """Les adresses masquées par Cloudflare (/cdn-cgi/l/email-protection#...)."""
    cle = int(hexa[:2], 16)
    return "".join(chr(int(hexa[i:i + 2], 16) ^ cle) for i in range(2, len(hexa), 2))


def _extrait(page):
    corps = re.sub(r"<(script|style|noscript|nav|header|footer|svg)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return texte(corps)[:TEXTE_SITE_MAX]


def adresses_du_site(op):
    if not op.get("site"):
        return
    domaine = urlparse(op["site"]).netloc.lower().removeprefix("www.")
    op["domaine"] = domaine
    trouvees = set()
    for page in PAGES:
        r = get(urljoin(op["site"].rstrip("/") + "/", page), timeout=10)
        if not r:
            continue
        if page == "":
            m = re.search(r'<meta[^>]+(?:name="description"|property="og:description")[^>]+content="([^"]+)"', r.text) \
                or re.search(r'<meta[^>]+content="([^"]+)"[^>]+(?:name="description"|property="og:description")', r.text)
            op["pitch"] = texte(m.group(1))[:220] if m else ""
            op["texte_site"] = _extrait(r.text)
        # Les scripts citent des adresses qui ne sont pas des contacts (suivi,
        # exemples de code) : on ne lit que le contenu. Les adresses masquées
        # par Cloudflare sont dans des liens, elles restent.
        contenu = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", r.text, flags=re.S)
        brut = contenu + " " + " ".join(decode_cf(h) for h in re.findall(r"email-protection#([0-9a-f]+)", contenu))
        for a in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", brut):
            a = a.lower().rstrip(".")
            if a.endswith("@" + domaine) or a.split("@")[1].endswith("." + domaine):
                trouvees.add(a)
    locales = {a.split("@")[0] for a in trouvees}
    op["adresses_recrutement"] = sorted(a for a in trouvees if a.split("@")[0] in RECRUTEMENT)
    op["adresses_generiques"] = sorted(a for a in trouvees
                                       if a.split("@")[0] in GENERIQUES and a not in op["adresses_recrutement"])
    personnelles = [l for l in locales
                    if l not in GENERIQUES | RECRUTEMENT and re.fullmatch(r"[a-z]+([.-][a-z]+)?", l)]
    op["adresses_nominatives"] = sorted(l + "@" + domaine for l in personnelles)
    if any("." in l for l in personnelles):
        op["format_adresse"] = "prenom.nom"
    elif personnelles:
        op["format_adresse"] = "prenom"


def mx(domaine):
    d = _json(get(DNS, params={"name": domaine, "type": "MX"}, headers={"Accept": "application/dns-json"}))
    return bool((d or {}).get("Answer"))


def _ascii(t):
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower())


def adresses_probables(op):
    """prenom@ d'abord, prenom.nom@ ensuite, sauf si le site a montré le format."""
    if not op.get("domaine"):
        return
    op["mx"] = "oui" if mx(op["domaine"]) else "non"
    formats = [op["format_adresse"]] if op.get("format_adresse") else ["prenom", "prenom.nom"]
    for d in op.get("dirigeants") or []:
        p, n = _ascii(d["prenom"]), _ascii(d["nom"])
        if not p:
            continue
        d["adresses"] = [{"prenom": p, "prenom.nom": "{}.{}".format(p, n)}[f] + "@" + op["domaine"]
                         for f in formats]


def priorite(op):
    p = 0
    if op.get("recrute") or op.get("adresses_recrutement"):
        p += 3                                        # ils embauchent, c'est écrit
    if any(s in op.get("secteur", "").lower().split() for s in SECTEURS_PROCHES):
        p += 2
    if op.get("effectif_max") is not None and op["effectif_max"] <= 49:
        p += 1
    if any(d.get("adresses") for d in op.get("dirigeants") or []) or op.get("adresses_nominatives"):
        p += 1                                        # quelqu'un à qui écrire
    return p


# --------------------------------------------------------------------------
# La collecte


def collecter(semaines, avancement=lambda m: None):
    """Toute la chaîne, sans toucher à la base. Renvoie (retenues, écartées)."""
    rec = recaps(semaines)
    ops = [op for r in rec for op in operations(r)]
    avancement("{} récapitulatifs, {} opérations".format(len(rec), len(ops)))
    for i, op in enumerate(ops, 1):
        avancement("Fiches et registre : {}/{}".format(i, len(ops)))
        fiche(op)
        registre(op)
    retenues, ecartees = [], []
    for op in ops:
        dep = op.get("departement") or ""
        if dep and dep not in IDF:
            ecartees.append((op, "hors Île-de-France ({})".format(op.get("ville") or dep)))
        elif op.get("effectif_max") and op["effectif_max"] > EFFECTIF_MAX:
            ecartees.append((op, "effectif {}".format(op["effectif"])))
        else:
            retenues.append(op)
    for i, op in enumerate(retenues, 1):
        avancement("Sites et adresses : {}/{}".format(i, len(retenues)))
        adresses_du_site(op)
        adresses_probables(op)
        op["priorite"] = priorite(op)
    return retenues, ecartees


CHAMPS = ("semaine", "entreprise", "secteur", "montant", "investisseurs", "contexte", "ville",
          "departement", "creee", "effectif", "effectif_max", "siren", "raison_sociale", "naf",
          "registre", "site", "domaine", "pitch", "texte_site", "recrute", "format_adresse",
          "mx", "priorite", "fiche_maddyness")
LISTES = ("adresses_recrutement", "adresses_generiques", "adresses_nominatives", "dirigeants")


def enregistrer(ops):
    """Range les opérations retenues ; une entreprise déjà vue garde son
    statut et ses notes, ses faits sont rafraîchis. Renvoie le nombre de
    nouvelles."""
    nouvelles = 0
    for op in ops:
        l = Levee.query.filter_by(entreprise=op["entreprise"], semaine=op["semaine"]).first()
        if l is None:
            l = Levee(entreprise=op["entreprise"], semaine=op["semaine"])
            db.session.add(l)
            nouvelles += 1
        for c in CHAMPS:
            if c in op and op[c] is not None:
                setattr(l, c, op[c])
        for c in LISTES:
            setattr(l, c, json.dumps(op.get(c) or [], ensure_ascii=False))
    db.session.commit()
    return nouvelles


def _executer(collecte_id):
    c = db.session.get(CollecteLevees, collecte_id)
    if c is None:
        return

    def avancement(message):
        c.message = message
        db.session.commit()

    try:
        retenues, ecartees = collecter(c.semaines, avancement)
        c.nb_operations = len(retenues) + len(ecartees)
        c.nb_nouvelles = enregistrer(retenues)
        c.message = "{} opérations, {} en Île-de-France dont {} nouvelle{}, {} écartée{}".format(
            c.nb_operations, len(retenues), c.nb_nouvelles, "s" if c.nb_nouvelles > 1 else "",
            len(ecartees), "s" if len(ecartees) > 1 else "")
        c.etat = "terminee"
    except Exception as e:                           # jamais une collecte bloquée
        current_app.logger.exception("collecte des levées")
        c.etat, c.message = "erreur", "La collecte a échoué : {}".format(e)
    c.fin = datetime.now()
    db.session.commit()


def collecte_en_cours():
    c = CollecteLevees.query.filter_by(etat="en_cours").order_by(CollecteLevees.id.desc()).first()
    if c is not None and c.debut and datetime.now() - c.debut > ABANDON:
        c.etat = "erreur"
        c.message = "La collecte s'est interrompue, sans doute un redémarrage du serveur : relance-la."
        c.fin = datetime.now()
        db.session.commit()
        return None
    return c


def lancer_collecte(semaines=4):
    """Démarre la collecte en arrière-plan ; renvoie celle en cours s'il y en a une."""
    c = collecte_en_cours()
    if c is not None:
        return c
    c = CollecteLevees(semaines=max(1, min(int(semaines or 4), 12)), message="Démarrage")
    db.session.add(c)
    db.session.commit()
    lancer(_executer, c.id)
    return c


def derniere_collecte():
    return CollecteLevees.query.order_by(CollecteLevees.id.desc()).first()


# --------------------------------------------------------------------------
# Le mail


SKILL = (Path(__file__).resolve().parents[2]
         / ".claude" / "skills" / "mail-prospection" / "SKILL.md")
SCHEMA_MAIL = {
    "type": "object",
    "properties": {
        "resume": {"type": "string"},
        "objet": {"type": "string"},
        "paragraphes": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["resume", "objet", "paragraphes", "notes"],
    "additionalProperties": False,
}
SYSTEME = """{consignes}

# Les sources

<fiche_profil>
{profil}
</fiche_profil>

<cv>
{cv}
</cv>"""
DEMANDE = """<entreprise nom="{nom}">
- Levée : {montant}, récapitulatif du {semaine} ; investisseurs : {investisseurs}
- Secteur : {secteur} ; siège : {ville} ; créée en {creee} ; effectif : {effectif}
- Site : {site}
- Pitch du site : {pitch}
- Ce qu'en dit le récapitulatif : {contexte}
- Recrute : {recrute}
<texte_du_site>
{texte_site}
</texte_du_site>
</entreprise>

<destinataire>{destinataire}</destinataire>

<consigne_de_samuel>
{consigne}
</consigne_de_samuel>

Écris le résumé de l'entreprise pour Samuel, puis le mail à ce destinataire."""


def consignes():
    try:
        t = SKILL.read_text(encoding="utf-8")
    except OSError:
        raise LettreErreur("Le skill des mails de prospection est introuvable ({}).".format(SKILL))
    morceaux = re.split(r"^---\s*$", t, maxsplit=2, flags=re.M)
    return (morceaux[2] if t.startswith("---") and len(morceaux) == 3 else t).strip()


def _systeme(src):
    return SYSTEME.format(consignes=consignes(), profil=src["profil"], cv=src["cv"])


def _demande(mail, l):
    return DEMANDE.format(
        nom=escape(l.entreprise), montant=l.montant or "?", semaine=l.semaine or "?",
        investisseurs=l.investisseurs or "non précisés", secteur=l.secteur or "?",
        ville=l.ville or "?", creee=l.creee or "?", effectif=l.effectif or "non renseigné",
        site=l.site or "inconnu", pitch=l.pitch or "(aucun)", contexte=l.contexte or "(rien)",
        recrute="oui" if l.recrute or l.recrutement else "pas d'indication",
        texte_site=(l.texte_site or "(le site n'a pas pu être lu)").strip(),
        destinataire=escape(mail.destinataire or "le dirigeant"),
        consigne=(mail.consigne or "").strip() or "(aucune)")


def signature_par_defaut():
    """La dernière signature, sinon nom et coordonnées lus dans le modèle de lettre."""
    dernier = (MailProspection.query.filter(MailProspection.signature != "")
               .order_by(MailProspection.id.desc()).first())
    if dernier is not None:
        return dernier.signature
    lignes = [x for x in (lettres.expediteur_par_defaut() or "").splitlines() if x.strip()]
    if not lignes:
        return ""
    return "\n".join([lignes[0]] + [x for x in lignes[1:] if re.search(r"@|\d{2} ?\d{2} ?\d{2}", x)])


def nouveau_mail(l, destinataire, consigne=""):
    m = MailProspection(levee=l, destinataire=(destinataire or "").strip()[:200],
                        consigne=(consigne or "").strip(), signature=signature_par_defaut())
    db.session.add(m)
    db.session.commit()
    lancer(generer, m.id)
    return m


def generer(mail_id):
    """Écrit le résumé et le mail. Tourne en arrière-plan ; l'état dit où on en est."""
    m = db.session.get(MailProspection, mail_id)
    if m is None:
        return
    try:
        src = lettres.sources()
        manquants = [n for n, c in (("la fiche profil", "profil"), ("le CV ATS", "cv")) if not src[c]]
        if manquants:
            raise LettreErreur("Il manque sur le serveur : {}. Relance la synchronisation "
                               "(scripts/sync-jobs.ps1) depuis le PC.".format(", ".join(manquants)))
        data, meta = lettres._appel(_systeme(src), _demande(m, m.levee), SCHEMA_MAIL, "medium")
    except LettreErreur as e:
        m.etat, m.erreur = "erreur", str(e)
        db.session.commit()
        return
    except Exception as e:                           # jamais un mail bloqué
        current_app.logger.exception("mail de prospection %s", mail_id)
        m.etat, m.erreur = "erreur", "Erreur inattendue : {}".format(e)
        db.session.commit()
        return
    net = lettres._net
    m.resume = net(data.get("resume", "")).strip()
    m.objet = net(data.get("objet", ""))[:200]
    m.corps = "\n\n".join(net(p) for p in data.get("paragraphes", []) if p.strip())
    m.notes = net(data.get("notes", "")).strip()
    m.brouillon = json.dumps({"objet": m.objet, "corps": m.corps}, ensure_ascii=False)
    m.modele = (meta.get("modele") or "")[:40]
    m.jetons_entree, m.jetons_sortie = meta.get("entree", 0), meta.get("sortie", 0)
    m.etat, m.erreur = "pret", ""
    db.session.commit()


def abandonne(m):
    """Un redémarrage du serveur tue le fil qui écrivait : sans ce garde-fou,
    le mail resterait « en cours » pour toujours."""
    if m.etat != "generation" or m.updated_at is None or datetime.now() - m.updated_at < ABANDON:
        return False
    m.etat = "erreur"
    m.erreur = "La génération s'est interrompue, sans doute un redémarrage du serveur : relance-la."
    db.session.commit()
    return True


def texte_mail(m):
    """Le mail tel qu'il se colle : le corps, puis la signature."""
    return "\n\n".join(x.strip() for x in (m.corps, m.signature) if x and x.strip())


def mots(m):
    return len(re.findall(r"[\w'-]+", (m.corps or ""), re.U))
