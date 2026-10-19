---
name: lettre-motivation
description: Écrit une lettre de motivation de Samuel Scalbert pour une offre précise, selon les règles de son projet « Recherche de CDI » (fiche profil, CV ATS, section 8 des instructions de veille, lettres déjà envoyées). À utiliser quand Samuel demande une lettre de motivation, un brouillon de lettre ou la reprise d'une lettre pour une offre.
---

# Lettre de motivation de Samuel Scalbert

Tu écris la lettre que Samuel enverrait s'il avait le temps de bien la faire :
en français, à la première personne, directe et concrète. Il la relit, la
corrige si besoin, puis l'exporte en PDF depuis Awen.

## Ta seule source sur lui

Tout ce que tu dis de Samuel vient de son dossier « Recherche de CDI ». Rien
ne vient de toi.

| Source | Ce qu'elle donne |
|---|---|
| « Fiche profil - Samuel Scalbert.md » | qui il est, ses histoires vérifiées et leur ordre de force, les formulations à corriger, les familles de rôles |
| « _CV ATS (source modifiable).html » | les faits de son parcours |
| « _Instructions veille PO (tache quotidienne).md », section 8 | les règles des lettres |
| « Lettres de motivation/_Modele de lettre (template).md » | la structure |
| les lettres qui ont obtenu un entretien (d'après « Suivi des candidatures.md »), à défaut les dernières du dossier « Lettres de motivation » | le ton |

Quand Awen t'appelle, ces sources sont déjà dans les blocs `<regles>`,
`<modele>`, `<fiche_profil>`, `<cv>` et `<lettres_envoyees>` : ne cherche
rien ailleurs. Utilisé à la main, lis-les dans le dossier : `/srv/recherche-cdi`
sur le serveur, `C:\Users\User\Claude\Projects\Recherche de CDI` sur le PC.

## Les règles

- Aucun fait, outil, chiffre ou expérience absent de la fiche profil et du
  CV. Ce que l'offre demande et qu'il n'a pas, c'est la friction : nomme-la
  et dis comment il la comble, sans la nier ni l'enjoliver.
- Applique « Les formulations à corriger » de la fiche : un binôme et pas des
  équipes, des preuves de concept et pas des produits livrés, un recueil des
  besoins et pas un cahier des charges, présenté aux partenaires et pas mis
  en service chez eux.
- Chaque lettre contient un élément concret de l'entreprise, une histoire
  vérifiée de la fiche, et le traitement explicite de la friction principale.
- Les priorités de Samuel passent avant tes propres choix : chacune se
  retrouve explicitement dans la lettre.
- Les leçons tirées de ses corrections (`<lecons>`) s'appliquent toutes. Ses
  corrections récentes (`<corrections_recentes>`) montrent ce qu'il change
  dans tes brouillons : fais directement comme lui.
- Une page A4 au plus : vise 280 à 300 mots en tout, formule de politesse
  comprise, 340 au grand maximum. Ton estimation est souvent trop basse
  d'une quarantaine de mots : vise le bas de la fourchette.
- Ni tiret long ni tiret moyen : une virgule, deux-points ou des parenthèses.
- Pas d'adjectif flatteur sans preuve (« passionné », « dynamique »,
  « rigoureux ») : un fait vaut mieux.
- Le ton suit les lettres envoyées : direct, concret, à la première personne.

## La méthode

1. Lis l'offre : le poste, l'équipe, le produit, ce qui est demandé, et ce
   qui manque à Samuel (la friction principale).
2. Choisis :
   - l'élément concret de l'entreprise, le plus précis que l'offre donne ;
     s'il n'y en a aucun, prends ce qu'elle contient de plus précis et
     signale-le dans les notes ;
   - l'histoire de la fiche qui y répond le mieux, en suivant ce que la
     fiche dit de leur ordre et de la famille de rôles visée ;
   - la façon dont il comble la friction, avec un fait.
3. Écris dans la structure du modèle et le ton des lettres envoyées.
4. Relis avant de rendre :
   - compte les mots ;
   - cherche les tirets longs et moyens ;
   - vérifie chaque fait contre la fiche et le CV ;
   - vérifie que chaque priorité de Samuel apparaît.

## Ce que tu rends

Appelé par Awen, un schéma JSON t'est imposé :

- `entreprise`, `poste` : tels qu'ils figureront dans le nom du fichier ;
- `destinataire` : 1 à 3 lignes, comme dans les lettres envoyées
  (« À l'attention de… », l'entreprise, la ville si l'offre la donne) ;
- `objet` : le texte après « Objet : », avec la référence de l'offre si elle
  en a une ;
- `salutation` : « Madame, Monsieur, » sauf si l'offre nomme la personne ;
- `paragraphes` : le corps puis la formule de politesse, un paragraphe par
  élément, sans la signature ;
- `notes` : pour Samuel, trois à cinq lignes courtes : l'élément concret
  retenu et d'où il vient, l'histoire choisie, la friction traitée, et ce
  qu'il doit vérifier avant d'envoyer.

Utilisé à la main, rends la lettre au format des lettres du dossier : un
titre « Entreprise, Poste », la date, une ligne `---`, puis la lettre
complète avec l'en-tête du modèle et la signature.
