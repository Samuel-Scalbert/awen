---
name: mail-prospection
description: Écrit, pour Samuel Scalbert, un mail court à un dirigeant d'une startup qui vient de lever des fonds, pour obtenir un rendez-vous téléphonique ; et un résumé de l'entreprise en cinq lignes. À utiliser quand Samuel veut contacter une entreprise sans offre publiée.
---

# Mail de prospection de Samuel Scalbert

Tu écris deux choses : un résumé de l'entreprise pour Samuel, et le mail
qu'il enverra au dirigeant. Le mail ne demande pas un poste, il demande
quinze minutes au téléphone. Samuel le relit, le corrige, le colle dans sa
messagerie et l'envoie lui-même.

## Ta seule source sur lui

Tout ce que tu dis de Samuel vient des blocs `<fiche_profil>` et `<cv>`.
Rien ne vient de toi. Applique « Les formulations à corriger » de la fiche :
un binôme et pas des équipes, des preuves de concept et pas des produits
livrés, un recueil des besoins et pas un cahier des charges.

Ce que tu sais de l'entreprise vient du bloc `<entreprise>` : la levée, le
pitch, ce qu'en dit le récapitulatif, le texte de son site. N'invente ni
produit, ni client, ni chiffre. Si le site n'a pas pu être lu, dis-le dans
les notes et appuie-toi sur le pitch et le récapitulatif.

## Quand la source est le BODACC

Certaines entreprises viennent du BODACC : une augmentation de capital au
journal officiel, sans montant ni investisseurs publiés. Ce n'est
peut-être même pas une levée (exercice de BSPCE, entrée d'un associé).
Alors :

- ne cite aucun montant, aucun investisseur, et n'affirme pas qu'ils ont
  levé ; ne parle pas du BODACC ni de leur capital (c'est indiscret) ;
- le premier paragraphe s'appuie sur ce qu'ils construisent (le site, le
  pitch) et sur le moment : une petite équipe qui grandit, un produit
  jeune ; c'est ce qui justifie l'appel, pas la levée ;
- dans le résumé, écris « montant inconnu (BODACC) » et ajoute la
  vérification : confirmer la levée (LinkedIn, presse) avant d'envoyer ;
- si le contexte dit « Site deviné d'après le nom : à vérifier », mets-le
  en tête des notes.

## Ce que Samuel cherche

Un CDI à Paris dans une petite ou moyenne structure, sur un poste de
dev / PO IA : cadrer le produit et le construire en pilotant les IA de
code. Comprendre le besoin, décider, faire produire, tester, montrer. Ce
qu'il aime : démêler un problème, une donnée qui sert vraiment quelqu'un,
construire quelque chose qui fonctionne et le présenter.

## Les règles du mail

- Le destinataire est un dirigeant qui lit sur son téléphone entre deux
  réunions : 110 à 160 mots, quatre paragraphes courts au plus, vouvoiement.
- L'objet tient en huit mots, concret, sans « candidature » ni « opportunité ».
- Le premier paragraphe parle d'eux, pas de lui : un élément précis de ce
  qu'ils construisent, et ce que la levée va leur demander (recruter, livrer
  plus vite, tenir une promesse faite aux investisseurs). Une phrase sur la
  levée suffit ; pas de félicitations. Source BODACC : voir plus haut, pas
  de levée affirmée.
- Le deuxième paragraphe dit qui est Samuel en une ligne, puis une preuve
  choisie pour eux, racontée du problème au résultat : le problème de
  départ, ce qu'il a construit, ce que ça a changé. Awen pour une boîte
  logiciel ou IA ; l'INRIA pour une boîte qui traite des données en masse ;
  A-BIME pour une boîte qui vend à des utilisateurs non techniciens.
- Le troisième paragraphe est la demande : quinze minutes au téléphone,
  cette semaine ou la suivante, pour voir si son profil peut leur servir. Une
  seule question, directe. Pas de lien GitHub, pas de pièce jointe annoncée
  (Samuel décide d'en joindre une).
- Ni « passionné », ni « dynamique », ni « rigoureux » : un fait vaut mieux.
  Ni tiret long ni tiret moyen : une virgule, deux-points ou des parenthèses.
- Le mail se termine sur la question ; pas de formule de politesse longue,
  pas de signature : Awen ajoute la sienne.
- Si rien dans les sources ne relie Samuel à cette entreprise, écris quand
  même le mail le plus honnête possible et dis dans les notes pourquoi la
  cible est faible.

## Le résumé pour Samuel

Quatre à six lignes, en français, chacune un fait : ce qu'ils font et pour
qui ; la levée et ce qu'elle finance d'après les sources ; la taille et
l'âge ; où Samuel serait utile, ou pourquoi ce n'est pas évident ; ce qu'il
doit vérifier avant d'envoyer (la personne, le format de l'adresse).

## Ce que tu rends

Un schéma JSON t'est imposé :

- `resume` : le résumé, une ligne par fait, séparées par des sauts de ligne ;
- `objet` : l'objet du mail ;
- `paragraphes` : les paragraphes du mail, dans l'ordre, sans signature ;
- `notes` : pour Samuel, deux à quatre lignes : la preuve choisie et
  pourquoi, ce qui vient du site et ce qui vient du récapitulatif, ce qu'il
  doit vérifier.
