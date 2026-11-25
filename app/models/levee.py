"""Les levées de fonds et les mails de prospection.

Une entreprise qui vient de lever recrute : c'est le signal que Stanislas
Denis a donné à Samuel le 12/11/2026. Awen collecte les levées des startups
d'Île-de-France (services/levees.py), retrouve leurs dirigeants au registre,
et Claude écrit un mail court qui demande un rendez-vous téléphonique.

Ces tables contiennent des noms et des adresses de personnes : la base vit
dans data/, que git ignore, et rien n'en sort vers le dépôt public.
"""
import json
from datetime import datetime

from . import db

STATUTS = (("nouvelle", "Nouvelle"), ("a_contacter", "À contacter"),
           ("contactee", "Contactée"), ("repondu", "A répondu"),
           ("ecartee", "Écartée"))


def _liste(texte):
    try:
        v = json.loads(texte or "[]")
    except ValueError:
        return []
    return v if isinstance(v, list) else []


class CollecteLevees(db.Model):
    """Un passage de la collecte : quand, combien, et où il en est."""
    __tablename__ = "collectes_levees"

    id = db.Column(db.Integer, primary_key=True)
    debut = db.Column(db.DateTime, default=datetime.now)
    fin = db.Column(db.DateTime)
    semaines = db.Column(db.Integer, default=4)
    etat = db.Column(db.String(12), default="en_cours")   # en_cours / terminee / erreur
    message = db.Column(db.Text, default="")
    nb_operations = db.Column(db.Integer, default=0)
    nb_nouvelles = db.Column(db.Integer, default=0)
    # Les réglages du passage (25/11/2026) : viser les petites équipes.
    montant_max = db.Column(db.Integer)                   # en euros ; None = sans plafond
    equipe_max = db.Column(db.Integer)                    # borne haute de l'effectif ; None = sans limite
    sources = db.Column(db.String(40), default="maddyness,bodacc")


class Levee(db.Model):
    """Une entreprise qui vient de lever, et tout ce qu'on sait pour l'écrire."""
    __tablename__ = "levees"
    __table_args__ = (db.UniqueConstraint("entreprise", "semaine"),)

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    semaine = db.Column(db.String(10), default="")       # date du récapitulatif
    entreprise = db.Column(db.String(120), nullable=False)
    secteur = db.Column(db.String(80), default="")
    montant = db.Column(db.String(30), default="")
    investisseurs = db.Column(db.Text, default="")
    contexte = db.Column(db.Text, default="")            # ce qu'en dit le récapitulatif
    ville = db.Column(db.String(80), default="")
    departement = db.Column(db.String(3), default="")
    creee = db.Column(db.String(4), default="")
    effectif = db.Column(db.String(20), default="")
    effectif_max = db.Column(db.Integer)
    siren = db.Column(db.String(9), default="")
    raison_sociale = db.Column(db.String(200), default="")
    naf = db.Column(db.String(10), default="")
    registre = db.Column(db.String(120), default="")      # ok / probable / introuvable / douteux
    site = db.Column(db.String(300), default="")
    domaine = db.Column(db.String(120), default="")
    pitch = db.Column(db.Text, default="")
    texte_site = db.Column(db.Text, default="")
    recrute = db.Column(db.Boolean, default=False)
    adresses_recrutement = db.Column(db.Text, default="[]")
    adresses_generiques = db.Column(db.Text, default="[]")
    adresses_nominatives = db.Column(db.Text, default="[]")
    format_adresse = db.Column(db.String(12), default="")  # prenom / prenom.nom, lu sur le site
    mx = db.Column(db.String(3), default="")              # le domaine reçoit-il du courrier
    dirigeants = db.Column(db.Text, default="[]")         # [{prenom, nom, qualite, adresses}]
    priorite = db.Column(db.Integer, default=0)
    fiche_maddyness = db.Column(db.String(300), default="")
    # « maddyness » : un récapitulatif publié, montant connu. « bodacc » : une
    # augmentation de capital au journal officiel, montant inconnu.
    source = db.Column(db.String(10), default="maddyness")
    capital = db.Column(db.String(30), default="")        # le capital après l'opération (BODACC)
    annonce = db.Column(db.String(300), default="")       # le lien de l'annonce BODACC
    statut = db.Column(db.String(12), default="nouvelle")
    notes = db.Column(db.Text, default="")

    mails = db.relationship("MailProspection", backref="levee",
                            cascade="all, delete-orphan",
                            order_by="MailProspection.id.desc()")

    @property
    def recrutement(self):
        return _liste(self.adresses_recrutement)

    @property
    def generiques(self):
        return _liste(self.adresses_generiques)

    @property
    def nominatives(self):
        return _liste(self.adresses_nominatives)

    @property
    def dirigeants_liste(self):
        return _liste(self.dirigeants)

    @property
    def statut_libelle(self):
        return dict(STATUTS).get(self.statut, self.statut)

    @property
    def destinataires(self):
        """Tout ce à quoi on peut écrire, le plus personnel d'abord."""
        out = []
        for d in self.dirigeants_liste:
            for a in d.get("adresses") or []:
                out.append("{} {} ({}) <{}>".format(d.get("prenom", ""), d.get("nom", ""),
                                                   d.get("qualite", ""), a).replace("  ", " "))
        out += ["<{}>".format(a) for a in self.nominatives]
        out += ["<{}>".format(a) for a in self.recrutement + self.generiques]
        return out


class MailProspection(db.Model):
    """Un mail écrit par Claude pour un dirigeant, corrigé puis envoyé par Samuel."""
    __tablename__ = "mails_prospection"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    levee_id = db.Column(db.Integer, db.ForeignKey("levees.id"), nullable=False)

    destinataire = db.Column(db.String(200), default="")
    consigne = db.Column(db.Text, default="")            # ce que Samuel veut mettre en avant
    etat = db.Column(db.String(12), default="generation")  # generation / pret / erreur
    erreur = db.Column(db.Text, default="")
    resume = db.Column(db.Text, default="")              # le compte rendu de l'entreprise
    objet = db.Column(db.String(200), default="")
    corps = db.Column(db.Text, default="")
    signature = db.Column(db.Text, default="")
    notes = db.Column(db.Text, default="")
    brouillon = db.Column(db.Text, default="")           # JSON de la réponse de Claude
    modele = db.Column(db.String(40), default="")
    jetons_entree = db.Column(db.Integer, default=0)
    jetons_sortie = db.Column(db.Integer, default=0)
    envoye_le = db.Column(db.DateTime)
