from datetime import datetime

from . import db


class CoverLetter(db.Model):
    """Une lettre de motivation écrite avec Claude, puis corrigée par Samuel.

    Deux versions vivent côte à côte : `brouillon` garde ce que Claude a
    écrit, tel quel ; les champs éditables gardent ce que Samuel en a fait.
    C'est l'écart entre les deux qui sert de leçon pour les lettres
    suivantes : sans le brouillon d'origine, on ne saurait plus ce qui a été
    corrigé.

    La lettre est découpée comme la mise en page de ses lettres Word :
    expéditeur, date, destinataire, objet, salutation, corps. Le PDF n'a ainsi
    rien à deviner, et un corps modifié ne casse jamais l'en-tête.
    """
    __tablename__ = "cover_letters"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now,
                           onupdate=datetime.now)

    entreprise = db.Column(db.String(120), default="")
    poste = db.Column(db.String(200), default="")
    # Le texte de l'offre tel que Claude l'a lu, et d'où il vient : une offre
    # de la veille (« 2026-10-14#3 ») ou un texte collé à la main.
    offre = db.Column(db.Text, default="")
    offre_ref = db.Column(db.String(80), default="")
    priorites = db.Column(db.Text, default="")

    # attente, generation, prete, erreur
    etat = db.Column(db.String(12), default="attente")
    erreur = db.Column(db.Text, default="")

    expediteur = db.Column(db.Text, default="")
    date_ligne = db.Column(db.String(60), default="")
    destinataire = db.Column(db.Text, default="")
    objet = db.Column(db.String(300), default="")
    salutation = db.Column(db.String(120), default="")
    corps = db.Column(db.Text, default="")
    # Ce que Claude dit avoir utilisé, et ce qu'il faut vérifier avant d'envoyer.
    notes = db.Column(db.Text, default="")

    brouillon = db.Column(db.Text, default="")     # JSON de la réponse de Claude
    modele = db.Column(db.String(40), default="")
    jetons_entree = db.Column(db.Integer, default=0)
    jetons_sortie = db.Column(db.Integer, default=0)

    exportee_le = db.Column(db.DateTime)
    # Empreinte de la version dont les leçons ont déjà été tirées : exporter
    # deux fois la même lettre ne doit pas payer deux fois la même analyse.
    lecons_pour = db.Column(db.String(64), default="")


class LetterLesson(db.Model):
    """Une règle que Claude a tirée des corrections de Samuel.

    Elle entre dans chaque génération suivante tant qu'elle est active. Samuel
    les voit toutes et peut en retirer une : une leçon fausse, appliquée en
    silence à chaque lettre, ferait plus de dégâts que pas de leçon du tout.
    """
    __tablename__ = "letter_lessons"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    texte = db.Column(db.String(400), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    lettre_id = db.Column(db.Integer, db.ForeignKey("cover_letters.id"))
