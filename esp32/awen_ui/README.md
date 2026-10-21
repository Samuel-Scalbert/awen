# Afficheur Awen, firmware MicroPython

Trois pages (Accueil, Spotify, Calendrier) dessinées dans Lopaka, dont les
maquettes sont dans [`esp32/mockups/lopaka/`](../mockups/lopaka/), et
transposées en MicroPython pour le pilote `st7789_min.py`
d'esp32-desk-display. Dessin au pixel, polices avec accents, redessin
partiel.

```
theme.py     les couleurs, en RGB565
fonts.py     les polices bitmap   <- genere, ne pas editer
canvas.py    dessin au pixel + redessin partiel  <- le coeur
backlight.py luminosite du panneau (PWM) + extinction
presence.py  sonar HC-SR04 : quelqu'un est-il la ?
input.py     3 boutons + encodeur rotatif
screens.py   les 3 pages
app.py       navigation, reseau, boucle principale
main.py      cablage materiel  <- le seul fichier a adapter
```

Hors de la carte, [`esp32/simulateur.py`](../simulateur.py) fait tourner ces
mêmes fichiers sur le PC : voir « Vérifier sans flasher » plus bas.

## Ce que le firmware suppose

Écrit contre **ton pilote maison `st7789_min.py`** du dépôt
[esp32-desk-display](https://github.com/Samuel-Scalbert/esp32-desk-display).
`canvas.py` n'appelle que **trois** de ses méthodes :

```python
tft.fill_rect(x, y, largeur, hauteur, couleur)
tft.blit_buffer(tampon, x, y, largeur, hauteur)
tft.draw_image_file(chemin, x, y, largeur, hauteur)   # la pochette
```

### Le bus de l'écran tourne à 40 MHz, pas 80

`tft_setup.py` ouvre le SPI à 80 MHz, au-delà des 62,5 MHz que le ST7789
accepte en écriture. Sur les fils d'une breadboard, des bits se perdaient :
de petits traits de couleur apparaissaient là où le firmware avait peint du
noir, et y restaient, puisqu'il ne repeint que ce qui change. `main.py`
ramène donc le bus à 40 MHz avant de lancer l'application, et la console
l'affiche au démarrage :

```
ecran : SPI(id=2, baudrate=40000000, ...)
```

Par sécurité, `app.py` repeint aussi la page en place toutes les dix
minutes, sans effacer l'écran : un pixel abîmé ne survit pas longtemps.

### Les polices ne viennent plus du pilote

Le pilote n'a qu'une police, une 8×8 sans accents. Elle a porté les sept
écrans d'avant, sur une grille de 30 × 20 caractères. Elle ne peut pas porter
un agenda, où l'on lit « Séance » et « Réunion ».

`fonts.py` en embarque cinq, dix kilo-octets en tout :

| Nom | Ce que c'est | Où elle sert |
| --- | --- | --- |
| `S9` | FreeSans, 13 px de capitale, avec accents | le texte courant |
| `B9` | FreeSans gras, chiffres seuls | les heures de l'agenda |
| `B12` | FreeSans gras, 17 px, avec accents | le titre de la piste, le mois |
| `B18` | FreeSans gras, 25 px, chiffres seuls | les températures, le volume |
| `PX` | capitale 5×7 | les libellés |

Le fichier est **généré** par `scripts/gen_fonts.py`, à partir de GNU
FreeFont. Pour ajouter un caractère ou une taille, c'est le générateur qu'on
modifie :

```powershell
python scripts\gen_fonts.py dossier_contenant_FreeSans.ttf
```

L'heure de l'accueil, elle, n'est pas une police : sept pilules par chiffre,
allumées ou éteintes, comme sur un instrument. Les éteintes restent
visibles, à peine. Chaque segment est un élément du canevas : quand la minute
change, seuls ceux qui changent d'état sont repeints.

## Câblage complet

| Élément | Broche ESP32 | Alimentation |
| --- | --- | --- |
| **Écran** CS | 5 | **3V3** |
| Écran DC | 17 | |
| Écran RST | 21 | |
| Écran rétroéclairage | 22 | piloté en PWM par `backlight.py` (luminosité + veille) |
| Écran SCK | 18 | |
| Écran MOSI | 23 | |
| **Bouton A** gauche | 26 | vers **GND** |
| **Bouton B** sélection | 27 | vers **GND** |
| **Bouton C** droite | 14 | vers **GND** |
| **Encodeur** CLK | 4 — marqué `D4` | commun (patte du milieu) vers **GND** |
| Encodeur DT | 19 — marqué `D19` | |
| Encodeur poussoir | 16 — marqué **`RX2`** | l'autre patte vers **GND** |
| **LED RGB** rouge | 32 | ⚠️ **220 Ω en série** |
| LED RGB verte | 33 | ⚠️ **220 Ω en série** |
| LED RGB bleue | 13 | ⚠️ **220 Ω en série** |
| LED RGB commun | — | **GND** (cathode commune) ou **3V3** (anode) |
| **DHT11** DATA | 25 | ⚠️ **10 kΩ vers VCC**, plus **3V3** et **GND** |
| **HC-SR04** TRIG | 15 | VCC sur **VIN (5 V)**, pas 3V3 |
| HC-SR04 ECHO | 34 | ⚠️ **pont diviseur obligatoire** — voir plus bas |

Broche encore libre : **35** (`D35`, en entrée seule et sans tirage interne
— jamais pour un bouton).

> ### L'ECHO du HC-SR04 sort du 5 V
>
> Le module s'alimente en 5 V, et son `ECHO` ressort donc à 5 V. Les GPIO de
> l'ESP32 ne tolèrent pas plus de 3,6 V : en direct, la broche s'abîme — pas
> toujours d'un coup, ce qui est pire, car la panne arrive des semaines plus
> tard et ne ressemble plus à sa cause.
>
> Un pont diviseur, **1 kΩ et 2 kΩ** :
>
> ```
>    ECHO (5V) ──[1k]──┬── GPIO 34
>                      │
>                    [2k]
>                      │
>                     GND
> ```
>
> `5 × 2/(1+2) = 3,33 V`, pour 1,7 mA. **5k + 10k** donne exactement la même
> tension en tirant cinq fois moins de courant, si ces valeurs-là sont plus
> faciles à trouver dans le tiroir.
>
> Deux pièges dans les combinaisons qui ont l'air raisonnables :
>
> | Pont | Sortie | Verdict |
> | --- | --- | --- |
> | 1k + 2k | 3,33 V | ✅ |
> | 5k + 10k | 3,33 V | ✅ |
> | 2k + 5k | 3,57 V | ⚠️ à 30 mV du maximum toléré |
> | 10k + 10k | 2,50 V | ❌ 25 mV au-dessus du seuil haut |
> | 100k + 200k | 3,33 V | ❌ fronts trop mous, impédance trop haute |
>
> Le 10k + 10k est le plus tentant et le pire : 2,50 V passe le seuil de 2,475 V
> avec 25 mV de marge, donc ça marche au banc puis un jour sur deux une fois
> le fil rallongé. Rien n'est plus long à diagnostiquer qu'un montage qui
> marche presque.
>
> La variante **HC-SR04P** (ou RCWL-1601) accepte 3,3 V et se branche sans
> rien autour. Vérifie la sérigraphie avant de sortir les résistances.

### La sérigraphie ne dit pas toujours le numéro

Sur la DevKit 30 broches, deux GPIO ne portent pas de nom en `D` :

| GPIO | Marqué sur la carte |
| --- | --- |
| **16** | `RX2` |
| **17** | `TX2` — déjà pris, c'est le DC de l'écran |

Ce sont des GPIO comme les autres : MicroPython n'ouvre pas UART2 de
lui-même. Chercher « D16 » sur la carte ne donne rien, et fait conclure à
tort que la broche n'existe pas.

### Où est le 5 V, et pourquoi tu n'en as pas besoin

Sur une carte ESP32 DevKit la broche s'appelle **VIN** (parfois **5V**), en
général en tête de rangée à côté de GND. Alimentée par l'USB, elle sort
environ 4,7 V.

**Rien ici n'en a besoin, et le DHT11 ne doit surtout pas y aller** :
alimenté en 5 V il mettrait 5 V sur sa ligne DATA, reliée directement à un
GPIO qui ne tolère que 3,6 V. L'entrée s'abîme, parfois lentement — le genre
de panne qui se manifeste des semaines plus tard, sans lien apparent.

La LED RGB est passive : ses trois pattes sont pilotées par les GPIO, seul
le commun est câblé, au GND ou au 3V3 selon son type.

### Les résistances ne sont pas facultatives

Une LED sans limitation tire tout ce qu'elle peut. Un GPIO d'ESP32 donne
12 mA confortablement et 40 mA en absolu : sans résistance, la LED **et** la
sortie se dégradent. **220 Ω sur chaque patte de couleur**, jamais une seule
sur le commun — elle ferait varier la couleur selon le nombre de canaux
allumés.

### Cathode ou anode commune

La patte la plus longue est le commun. Pour trancher : relie-la au GND et
touche une patte de couleur au 3V3 à travers 220 Ω. Si ça s'allume, c'est
une **cathode commune** — le cas le plus répandu, et la valeur par défaut.

Si les couleurs sortent à l'envers (l'accueil devrait être orange et sort
cyan), mets `LED_COMMON = "anode"` dans `main.py`.

## Détail des entrées

Les boutons se câblent **entre le GPIO et la masse**, sans résistance : le
tirage interne est activé dans `input.py`. Un bouton relâché lit donc 1, un
bouton enfoncé lit 0. Aucune polarité à respecter, un bouton n'a pas de sens.

L'encodeur se câble comme trois boutons de plus : **CLK**, **DT** et le
poussoir vers leurs GPIO, le **commun** vers la masse. Aucune résistance,
aucune alimentation — les tirages internes sont activés dans `input.py`, et
un encodeur mécanique n'est qu'une paire de contacts. Sur l'Adafruit, le
commun est la patte du milieu du côté à trois pattes ; les deux autres sont
CLK et DT, et les intervertir ne fait qu'inverser le sens de rotation.

```
        ESP32                        ENCODEUR
   ┌───────────────┐            ┌──────────────────┐
   │         GPIO4 ├────────────┤ CLK              │
   │        GPIO19 ├────────────┤ DT               │
   │        GPIO16 ├────────────┤ poussoir         │
   │           GND ├────┬───────┤ commun + l'autre │
   │               │    │       │ patte du poussoir│
   │               │    │       └──────────────────┘
   │        GPIO26 ├───[A]───┤     A = gauche
   │        GPIO27 ├───[B]───┤     B = milieu
   │        GPIO14 ├───[C]───┘     C = droite
   └───────────────┘
                        tout partage la meme masse
```

L'écran, lui, vient de `tft_setup.py`, déjà « le seul endroit où vivent les
numéros de broches » : CS 5, DC 17, RST 21, rétroéclairage 22, SCK 18,
MOSI 23, SPI 2 à 80 MHz. Ce firmware l'importe au lieu de le redéclarer.

> ### Pourquoi 4, 19 et 16 pour l'encodeur
>
> CLK et DT doivent être lus **par interruption** et avoir un **tirage
> interne** : cela exclut d'emblée 34 à 39, qui sont en entrée seule. Il faut
> aussi éviter les broches de démarrage — **GPIO 12** fixe la tension de la
> flash au reset, et un encodeur qui la maintient au niveau haut pendant que
> tu rallumes la carte peut la rendre muette.
>
> GPIO 4 et 19 sont libres, tirables et sans rôle au boot. Le poussoir va
> sur **16**, qui n'a pas de nom en `D` sur la carte : cherche `RX2`.

## Carte des boutons

Une seule règle, valable partout, sans exception :

```
   [A] gauche          [B] milieu           [C] droite
    GPIO 26             GPIO 27              GPIO 14

   page precedente    action de la page    page suivante
                      ─────────────────
                      maintenu : ACCUEIL
```

**A et C naviguent toujours.** C'est ce qui garantit qu'aucune page ne peut
te piéger. **B agit**, et maintenu il ramène à l'accueil depuis n'importe où.

Le carrousel : **Accueil → Spotify → Calendrier**, puis retour au début. Le
pied de chaque page dit où mènent A et C.

### Ce que font B et la molette, page par page

| Page | Appui court sur B | La molette |
| --- | --- | --- |
| **Accueil** | rien | **la luminosité** |
| **Spotify** | lecture / pause | **le volume** |
| **Calendrier** | revient à aujourd'hui | fait défiler les jours |

B est inactif sur l'accueil, et c'est assumé : y coller une action pour
qu'il « serve » créerait un geste qu'on déclenche par erreur. Un bouton
inerte se remarque moins qu'un bouton qui fait quelque chose d'inattendu.

Deux gestes en plus, uniquement sur Spotify :

| Geste | Effet |
| --- | --- |
| **A maintenu** | piste précédente |
| **C maintenu** | piste suivante |

Maintenir plutôt que taper, parce que l'appui court d'A et de C doit rester la
navigation partout. Les faire changer de piste enfermerait dans Spotify : les
trois boutons seraient pris et seul l'appui long en sortirait. C'est aussi le
geste des autoradios. La page le rappelle sous ses pictogrammes :
`A TENU` et `C TENU`.

La pochette fait 144 px, et la colonne à sa droite porte le volume : sa
valeur et une jauge verticale, un pixel par pour cent. La carte demande
cette taille au serveur (`/cover?size=144`), qui la lui sert nette ; sans
paramètre, il sert toujours l'ancienne pochette de 112 px en blocs.

**Les boutons trient, la molette règle.** C'est ce partage qui rend trois
boutons suffisants.

## Couleurs et luminosité

Une seule teinte, le bleu. Les maquettes étaient en ambre ; sur le panneau
l'ambre tirait au jaune, et le bleu l'a remplacé. Neuf rôles dans
`theme.py` : le fond, l'accent (l'heure, ce qui est en cours), l'encre des
valeurs, les libellés, l'alerte, les segments éteints, les filets, les
repères inactifs, ce qui est déjà passé.

Les rôles sombres sont plus clairs qu'ils n'en ont l'air sur un PC : le
panneau écrase le bas de l'échelle, et les repères de page des maquettes y
étaient invisibles. Une couleur se juge sur la carte.

Les six palettes au choix sont parties avec l'écran Thème. Une teinte qu'on
n'a jamais vue sur ces pages ne peut pas être promise lisible : en rajouter
une, c'est écrire une seconde `Palette` et la regarder dans le simulateur
avant de la proposer.

### La luminosité est sur la molette de l'accueil

Elle n'avait plus de page à elle, et la molette n'avait rien à faire sur
l'accueil. Un cran vers la droite monte d'un palier, un cran vers la gauche
en descend. Le palier s'affiche deux secondes dans le bandeau, à la place du
sonar :

```
LUMIERE 70%
```

Quatre paliers, **15, 40, 70, 100 %**, plutôt qu'un pourcentage libre : on
ne saurait pas viser une valeur qu'on ne sait pas nommer, alors que quatre
crans couvrent la nuit, la pièce éclairée, la journée et le plein soleil.

**Zéro n'est pas dans la liste.** Un écran éteint par un cran de trop
ressemblerait à une panne, et on en chercherait la cause au lieu de la
molette. L'extinction complète appartient à la veille, qui a une raison de
la déclencher et sait la défaire : `Backlight` garde d'ailleurs son niveau
pendant l'extinction, pour y revenir au réveil.

Le réglage est enregistré dans `awen_backlight.txt`, et survit donc à une
coupure de courant.

## La veille

Personne devant le bureau pendant **dix minutes** : le rétroéclairage et la
LED s'éteignent. Quelqu'un revient : tout se rallume immédiatement.

```python
PRESENCE_CM      = 120      # sous ce seuil, quelqu'un est là
PRESENCE_IDLE_MS = 600000   # 10 minutes de vide avant l'extinction
```

**Le seuil se mesure, il ne se devine pas.** Il dépend d'où le capteur est
posé et de la profondeur du bureau. Relevé ici : assis **70 à 75 cm**, bureau
vide **235 cm**. 120 cm tombe largement entre les deux. `upload.ps1 -Test`
refait la mesure et propose la valeur.

### Deux lectures d'accord, jamais une seule

Un sonar renvoie des aberrations — un écho sur le bord du bureau, une salve
perdue dans un angle. Une mesure isolée ne décide donc de rien : il en faut
deux consécutives qui disent la même chose. Sans ce filtre, un faux
« présent » relancerait le compte à rebours en boucle et l'écran ne
s'éteindrait jamais.

Une mesure **ratée** (aucun écho) est **ignorée**, pas interprétée : le
capteur manque un vêtement sombre ou une surface oblique, et c'est le cas
normal. Elle réinitialisait la chaîne de confirmation, et un mur qui ne
répond qu'une fois sur deux suffisait alors à ce que plus rien ne soit jamais
confirmé — l'écran s'éteignait par expiration du délai et ne se rallumait
plus jamais.

Pour la même raison, le réveil suit **l'état** de présence et non la
transition : un front manqué une seule fois laissait l'écran noir
indéfiniment, alors que lire l'état ne peut rien rater — au pire on regarde
une demi-seconde trop tard. L'endormissement oublie explicitement la
présence, sans quoi l'écran se rallumerait aussitôt sur une détection que le
délai vient de déclarer périmée.

### L'asymétrie est voulue

Le réveil est immédiat, le sommeil attend le délai complet. Se tromper en
rallumant coûte une lampe allumée pour rien ; se tromper en éteignant coupe
l'écran sous le nez de quelqu'un.

**Un appui sur n'importe quel bouton réveille aussi**, et ce geste-là ne fait
*que* réveiller — il ne change pas d'écran et ne lance pas de piste. Le sonar
peut rater quelqu'un d'immobile ou assis de biais ; sans cette porte de
sortie, l'écran resterait noir sous les doigts de son propriétaire.

### Ce que la veille n'arrête pas

Le wifi, les relevés serveur et l'horloge continuent. Au réveil, l'écran doit
être **juste**, pas se rafraîchir sous les yeux : un afficheur qui montre
l'heure d'il y a dix minutes le temps de se recharger serait pire que celui
qui n'aurait jamais dormi.

Ce qui s'arrête, c'est le **dessin**. Pousser des pixels sur un panneau noir
ne sert personne, et le logo cesse de tourner. Le panneau garde son image :
au réveil, le canevas n'envoie que ce qui a réellement changé.

`Backlight` conserve son niveau pendant l'extinction, pour y revenir au
réveil au lieu d'un palier arbitraire.

### Ce que le sonar voit, écrit sur l'accueil

Dans le bandeau, à droite, là où les autres pages mettent l'heure :

```
72/120 CM
```

La distance mesurée, puis le seuil. Deux nombres qui répondent aux deux
seules questions qu'on se pose devant une veille qui se déclenche mal :
**me voit-il ?** et **à partir de quelle distance ?** Sans eux, le
`PRESENCE_CM` de `main.py` est un nombre qu'on ne peut confronter à rien.

La distance s'allume en ambre quand elle passe sous le seuil, ce qui répond à
la première question sans avoir à comparer les deux nombres. Un écho perdu
s'affiche `--` et non `0` : zéro ferait croire à un obstacle collé au
capteur, soit exactement l'inverse de ce qui se passe.

Hors ligne, cette place est prise par l'annonce `HORS LIGNE`, qui compte
davantage.

## Animations

Trois rythmes, dans `app.py` :

```python
BOOT_STEP_MS = 300   # apparition d'une ligne d'amorcage
SWEEP_MS     = 14    # une ligne du balayage de transition
SPIN_MS      = 150   # une image du logo
```

**L'amorçage** révèle ses lignes une par une, à cadence fixe. Le rythme ne
doit rien devoir au réseau : c'est une animation, pas une barre de
progression.

**Le changement de page** balaye une ligne lumineuse du haut vers le bas.
Repeindre les 240×320 d'un coup produit un flash noir qui se lit comme un gel
de l'affichage : rien ne bouge, puis tout a changé. Le balayage prend le même
temps mais raconte ce qui se passe.

**Le logo** tourne dans le bandeau de toutes les pages, huit images en 1,2
seconde. C'est le seul mouvement permanent : sans lui, une page qui ne change
qu'une fois par minute ne se distingue pas d'une page gelée. Plus vite, il se
lirait comme un sablier, donc comme une attente.

Il ne repasse pas par le dessin de la page : `app.py` demande directement
l'image suivante au canevas, un envoi de 16×16 pixels. Et il s'arrête pendant
la veille, où il n'a rien à dire à personne.

## La molette n'envoie qu'un déplacement

`input.py` émet `(TURN, +1)` ou `(TURN, -1)`, jamais une position. L'écran
courant reçoit ce cran et l'applique à ce qu'il affiche déjà.

C'est ce qui rend le firmware plus simple qu'avec le potentiomètre qu'il y
avait avant. Un potard a une position physique que le firmware ne peut pas
changer : réglé à 75 % sur les Paramètres, il aurait collé le volume de
Spotify à 75 % dès l'arrivée sur l'écran, sans que tu touches rien. Il avait
donc fallu un mécanisme de rattrapage — le curseur ne reprenait la main
qu'après avoir traversé la valeur courante — plus un repère `TOURNE >` pour
qu'on ne croie pas la molette cassée, plus un réarmement à chaque changement
d'écran et à chaque changement de ligne.

Tout cela a disparu avec le composant. Et avec lui la calibration
automatique, la zone morte et le lissage : trois filtres qui n'existaient
que pour dompter une tension analogique. Un contact mécanique n'a besoin que
de la table de quadrature, qui absorbe les rebonds en ignorant les
transitions impossibles.

## Installation

```powershell
Copy-Item awen_config.example.py awen_config.py   # URL + cle d'API
notepad awen_config.py
.\upload.ps1                                      # trouve le port tout seul
.\upload.ps1 -Console                             # + la sortie de la carte
```

`st7789_min.py`, `tft_setup.py`, `wifi.py` et `wifi_config.py` doivent déjà
être sur la carte — ils viennent d'esp32-desk-display et ne sont pas dupliqués
ici. `upload.ps1` vérifie leur présence et refuse de continuer sinon, plutôt
que de te laisser découvrir un `ImportError` sur un écran noir.

**Le wifi n'est pas dans `awen_config.py`.** Il vient de `wifi_config.py`,
déjà sur la carte et déjà utilisé par `wifi.py` et `spotify_screen.py`. Un mot
de passe dupliqué finit desynchronisé, ou publié.

`awen_config.py` ne contient donc que l'URL du serveur et la clé d'API. Il est
dans le `.gitignore`, ne le versionne jamais, et `ESP32_API_KEY` doit
correspondre exactement au `.env` du serveur.

## Ce que lit le firmware

Un seul appel, `GET /api/esp32/pages`, toutes les trente secondes (cinq sur
Spotify). Le serveur y prépare tout, **déjà trié et étiqueté** : c'est du
travail en moins pour un interpréteur MicroPython.

| Bloc | Ce qu'il contient | D'où il vient |
| --- | --- | --- |
| `min`, `sec` | l'heure, à la seconde | l'horloge du serveur |
| `jour` | la date en toutes lettres, le numéro de semaine | idem |
| `meteo` | température, mini, maxi, pluie, état du ciel en dix caractères | Open-Meteo, gardé une demi-heure |
| `agenda` | les quatre lignes de l'accueil, les jours à venir, la semaine | le flux ICS d'Awen, gardé cinq minutes |
| `spotify` | la piste, sa position, le volume, l'empreinte de la pochette | l'API Spotify |

La température et l'humidité de la pièce ne passent pas par le serveur : le
DHT11 est lu sur la carte.

### L'agenda vient du flux ICS

C'est le calendrier déjà branché sur Awen (`SAMSUNG_CALENDAR_ICS_URL`). Le
serveur le lit, déplie les évènements répétés (la séance du mardi revient
chaque mardi), convertit en heure locale et n'envoie que ce que l'écran
affiche.

Chaque ligne vaut `[heure, titre, état]`. L'heure est vide pour une journée
entière. L'état : 0 passé, 1 celui qu'on met en avant (en cours, ou le
prochain), 2 à venir. La carte ne compare aucune heure : elle colore selon
l'état, et c'est tout.

### L'heure avance toute seule

La carte n'a pas d'horloge sauvegardée. Le serveur donne l'heure à la seconde
près ; entre deux relevés, `app.minutes()` ajoute le temps écoulé. La minute
change donc à l'heure, et non jusqu'à trente secondes plus tard.

### Garde les jetons sur le serveur

L'afficheur ne parle ni à Spotify ni au calendrier. Le serveur détient les
jetons et l'adresse du flux ; la carte n'est qu'une télécommande sans secret,
à part sa clé d'API.

## Vérifier sans flasher

```powershell
python esp32\simulateur.py
```

Le simulateur fait tourner `app.py`, `screens.py` et `canvas.py` tels quels,
avec un faux écran, de fausses broches et un faux serveur. Il écrit les
pages dans `esp32/mockups/simulateur/`, à côté des maquettes Lopaka pour
comparer.

Surtout, il **rejoue les enchaînements qui piègent un redessin partiel** : la
température qui passe de 9 à 10, la pluie à 100 %, le calendrier qu'on fait
défiler, Spotify qui s'arrête, le serveur qui tombe. Après chacun, il compare
l'écran obtenu pas à pas avec le même écran repeint de zéro. Un seul pixel
d'écart arrête tout, et dit où.

Ce qu'il ne dit pas : la vitesse réelle du bus, la mémoire libre, le câblage.
Pour ceux-là il reste la carte, et `upload.ps1 -Console`.

## Quand la carte redémarre toute seule

L'écran d'amorçage qui revient sans qu'on ait touché à rien, c'est un vrai
redémarrage : une exception Python est rattrapée par la boucle et ne coûte
qu'une image. La console série s'efface à ce moment-là, donc la carte le dit
au serveur :

- chaque relevé de `/pages` porte son état : `up` (secondes depuis le
  démarrage), `mem` (tas MicroPython libre), `idf` et `bas` (tas de l'ESP-IDF,
  celui du wifi : libre, et le plus bas atteint), `p` (la page), `e` (erreurs
  rattrapées), `n` (relevés ratés) ;
- au démarrage, la cause donnée par la puce part vers `/api/esp32/journal`,
  et le serveur la range avec le dernier état d'avant ;
- une erreur de la boucle y part aussi, au plus une par minute.

Pour lire, depuis le PC ou le serveur :

```
curl "http://192.168.1.32:5000/api/esp32/journal?key=<ESP32_API_KEY>&n=20"
```

| Cause | Ce que ça veut dire | Où chercher |
| --- | --- | --- |
| `ALIM` | mise sous tension, ou chute de tension | câble USB, chargeur, port du PC qui se met en veille |
| `EN` | la broche de reset : le bouton, ou le PC | juste après un `upload.ps1` : rien d'anormal (c'est ainsi qu'il s'inscrit) ; sinon un PC qui ouvre le port série |
| `LOGICIEL` | erreur dans le C de MicroPython ou de l'ESP-IDF, ou `machine.reset()` | `bas` proche de zéro : le wifi manquait de mémoire ; sinon la console série |
| `GARDE` | un chien de garde de l'ESP-IDF : quelque chose a bloqué | un appel qui ne rend pas la main |

Un `ALIM` dont l'état d'avant est sain (mémoire stable, aucune erreur) ne
vient pas du code.

## Pourquoi le redessin partiel

Repeindre 240×320 coûte une trentaine de millisecondes en MicroPython. À
chaque minute d'horloge, ça clignoterait.

Dans `canvas.py`, chaque élément d'une page porte une **clé**, et le canevas
retient ce qu'il a tracé sous cette clé. Redemander la même chose ne coûte
qu'une comparaison ; demander autre chose ne repeint que cet élément. Une
page redit donc tout à chaque changement, sans chercher ce qui a bougé :
09:41 qui devient 09:42 ne coûte que les segments qui changent d'état.

Deux règles en découlent, et ce sont elles que le simulateur surveille :

- **Un élément qui disparaît se redit vide.** Un texte `""` efface l'ancien,
  une forme se repeint de la couleur du fond.
- **Ce qui s'efface passe avant ce qui s'écrit**, quand deux éléments
  partagent une place (l'heure d'un rendez-vous et la mention `JOURNEE`).
  Dans l'autre sens, l'effacement emporte le texte tout juste posé.

Au changement de page, `App.go()` appelle `sweep()`, qui oublie tout.

## Caractères

`S9` et `B12` écrivent l'ASCII et **les accents du français** : un agenda dit
« Séance » et « Réunion ». Le serveur ramène le reste à ce que la carte sait
tracer (`_latin()` dans `app/routes/esp32.py`) : une apostrophe courbe devient
droite, un emoji devient une espace.

**Les deux listes doivent rester identiques** : `ACCENTS` dans
`scripts/gen_fonts.py`, `_ACCENTS` côté serveur. Un caractère envoyé mais
absent de la police sortirait en point d'interrogation.

Les libellés en petites capitales (`PX`) restent sans accents : ils sont
écrits par le firmware, jamais par l'agenda, et une capitale s'en passe.
