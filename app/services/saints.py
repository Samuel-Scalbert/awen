"""Saint du jour, façon almanach français.

Une table embarquée plutôt qu'une API : c'est une donnée fixe, connue à
l'avance pour les 366 jours. Dépendre d'un service tiers pour un contenu qui
ne change jamais, c'est ajouter une panne possible sans rien gagner.

C'est l'almanach courant des agendas français, pas le calendrier liturgique
romain — les deux divergent sur plusieurs dates, et cette table suit le
premier, celui qu'on lit dans un calendrier des postes.

Février compte 29 entrées, pas 28 : une table de 365 jours décalerait tout à
partir du 1er mars des années bissextiles, et le décalage passerait inaperçu
pendant quatre ans.

Les noms sont sans accents — l'afficheur ESP32 a une police ASCII, et les y
retirer ici évite de le refaire à chaque lecture.
"""

# Un mois par ligne, les noms séparés par des virgules. Nettement plus
# compact et plus relisable qu'un dictionnaire de 366 entrées.
_MONTHS = (
    # Janvier
    "Marie,Basile,Genevieve,Odilon,Edouard,Melaine,Raymond,Lucien,Alix,"
    "Guillaume,Pauline,Tatiana,Yvette,Nina,Remi,Marcel,Roseline,Prisca,"
    "Marius,Sebastien,Agnes,Vincent,Barnard,Francois,Conversion,Paule,"
    "Angele,Thomas,Gildas,Martine,Marcelle",
    # Fevrier
    "Ella,Presentation,Blaise,Veronique,Agathe,Gaston,Eugenie,Jacqueline,"
    "Apolline,Arnaud,Notre-Dame,Felix,Beatrice,Valentin,Claude,Julienne,"
    "Alexis,Bernadette,Gabin,Aimee,Pierre-Damien,Isabelle,Lazare,Modeste,"
    "Romeo,Nestor,Honorine,Romain,Auguste",
    # Mars
    "Aubin,Charles,Guenole,Casimir,Olive,Colette,Felicite,Jean de Dieu,"
    "Francoise,Vivien,Rosine,Justine,Rodrigue,Mathilde,Louise,Benedicte,"
    "Patrice,Cyrille,Joseph,Herbert,Clemence,Lea,Victorien,Catherine,"
    "Annonciation,Larissa,Habib,Gontran,Gwladys,Amedee,Benjamin",
    # Avril
    "Hugues,Sandrine,Richard,Isidore,Irene,Marcellin,Jean-Baptiste,Julie,"
    "Gautier,Fulbert,Stanislas,Jules,Ida,Maxime,Paterne,Benoit-Joseph,"
    "Anicet,Parfait,Emma,Odette,Anselme,Alexandre,Georges,Fidele,Marc,"
    "Alida,Zita,Valerie,Catherine de S.,Robert",
    # Mai
    "Jeremie,Boris,Philippe,Sylvain,Judith,Prudence,Gisele,Desire,Pacome,"
    "Solange,Estelle,Achille,Rolande,Matthias,Denise,Honore,Pascal,Eric,"
    "Yves,Bernardin,Constantin,Emile,Didier,Donatien,Sophie,Beranger,"
    "Augustin,Germain,Aymar,Ferdinand,Visitation",
    # Juin
    "Justin,Blandine,Kevin,Clotilde,Igor,Norbert,Gilbert,Medard,Diane,"
    "Landry,Barnabe,Guy,Antoine de P.,Elisee,Germaine,Jean-Francois,Herve,"
    "Leonce,Romuald,Silvere,Rodolphe,Alban,Audrey,Jean-Baptiste,Prosper,"
    "Anthelme,Fernand,Irenee,Pierre et Paul,Martial",
    # Juillet
    "Thierry,Martinien,Thomas,Florent,Antoine,Mariette,Raoul,Thibaut,"
    "Amandine,Ulrich,Benoit,Olivier,Henri,Camille,Donald,Notre-Dame,"
    "Charlotte,Frederic,Arsene,Marina,Victor,Marie-Madeleine,Brigitte,"
    "Christine,Jacques,Anne et Joachim,Nathalie,Samson,Marthe,Juliette,"
    "Ignace de L.",
    # Aout
    "Alphonse,Julien,Lydie,Jean-Marie,Abel,Transfiguration,Gaetan,"
    "Dominique,Amour,Laurent,Claire,Clarisse,Hippolyte,Evrard,Assomption,"
    "Armel,Hyacinthe,Helene,Jean-Eudes,Bernard,Christophe,Fabrice,Rose,"
    "Barthelemy,Louis,Natacha,Monique,Augustin,Sabine,Fiacre,Aristide",
    # Septembre
    "Gilles,Ingrid,Gregoire,Rosalie,Raissa,Bertrand,Reine,Nativite,Alain,"
    "Ines,Adelphe,Apollinaire,Aime,La Sainte Croix,Roland,Edith,Renaud,"
    "Nadege,Emilie,Davy,Matthieu,Maurice,Constant,Thecle,Hermann,Come et D.,"
    "Vincent de P.,Venceslas,Michel,Jerome",
    # Octobre
    "Therese,Leger,Gerard,Francois d'A.,Fleur,Bruno,Serge,Pelagie,Denis,"
    "Ghislain,Firmin,Wilfried,Geraud,Juste,Therese d'A.,Edwige,Baudouin,"
    "Luc,Rene,Adeline,Celine,Elodie,Jean de C.,Florentin,Crepin,Dimitri,"
    "Emeline,Simon et Jude,Narcisse,Bienvenue,Quentin",
    # Novembre
    "Toussaint,Defunts,Hubert,Charles,Sylvie,Bertille,Carine,Geoffroy,"
    "Theodore,Leon,Martin,Christian,Brice,Sidoine,Albert,Marguerite,"
    "Elisabeth,Aude,Tanguy,Edmond,Presentation,Cecile,Clement,Flora,"
    "Catherine L.,Delphine,Severin,Jacques de la M.,Saturnin,Andre",
    # Decembre
    "Florence,Viviane,Francois-Xavier,Barbara,Gerald,Nicolas,Ambroise,"
    "Immaculee C.,Pierre Fourier,Romaric,Daniel,Chantal,Lucie,Odile,"
    "Ninon,Alice,Gael,Gatien,Urbain,Abraham,Pierre C.,Francoise-Xaviere,"
    "Armand,Adele,Noel,Etienne,Jean,Innocents,David,Roger,Sylvestre",
)

_TABLE = tuple(tuple(m.split(",")) for m in _MONTHS)


def of(day):
    """Le saint fêté à cette date. Chaîne vide si la table ne le connaît pas."""
    month = _TABLE[day.month - 1]
    idx = day.day - 1
    return month[idx] if idx < len(month) else ""
