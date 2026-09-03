# Afficheur Awen — firmware MicroPython

Les sept écrans de [`esp32/mockups.py`](../mockups.py), transposés en
MicroPython pour le pilote `st7789_min.py` d'esp32-desk-display. Grille 30×20,
police 8×8 sur un pas de 16, redessin partiel.

```
theme.py     palettes RGB565 (ambre, phosphore, glacier)
grid.py      grille 30x20 + redessin partiel  <- le coeur
backlight.py luminosite du panneau (PWM) + extinction
presence.py  sonar HC-SR04 : quelqu'un est-il la ?
input.py     3 boutons + encodeur rotatif
screens.py   les 7 ecrans
app.py       navigation, reseau, boucle principale
main.py      cablage materiel  <- le seul fichier a adapter
```

## Ce que le firmware suppose

Écrit contre **ton pilote maison `st7789_min.py`** du dépôt
[esp32-desk-display](https://github.com/Samuel-Scalbert/esp32-desk-display).
`grid.py` n'appelle que **deux** de ses méthodes :

```python
tft.text(chaine, x, y, color=..., bg=..., scale=1)   # police 8x8 integree
tft.fill_rect(x, y, largeur, hauteur, couleur)
```

### La grille, et pourquoi 20 lignes et pas 40

240 ÷ 8 = **30 colonnes**. La police intégrée de `framebuf` fait 8 pixels de
haut, ce qui donnerait 40 lignes — mais on prend un pas vertical de **16**,
soit 20 lignes avec 8 pixels de respiration.

Ce n'est pas du gâchis. Une 8×8 collée ligne contre ligne sur 40 lignes donne
un pavé illisible à un mètre, et l'écran est posé sur un bureau, pas tenu à la
main. L'interligne double est aussi ce qui donne aux terminaux leur allure :
TARS n'affiche jamais de texte serré.

L'heure de l'écran de veille passe par `scale=4` — le pilote multiplie le
glyphe 8×8, ce qui donne du 32×32 franchement pixelisé. C'est voulu.

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

   ecran precedent    action de l'ecran    ecran suivant
                      ─────────────────
                      maintenu : ACCUEIL
```

**A et C naviguent toujours.** C'est ce qui garantit qu'aucun écran ne peut
te piéger. **B agit**, et maintenu il ramène à l'accueil depuis n'importe où.

Le carrousel : **Accueil → Séance → Spotify → Coach → Jobs → Paramètres →
Thème**, puis retour au début.

### Ce que fait B, écran par écran

| Écran | Appui court sur B | La molette |
| --- | --- | --- |
| **Accueil** | — | — |
| **Séance** | — *(lecture seule)* | fait défiler les exercices |
| **Spotify** | lecture / pause | **le volume** |
| **Coach** | applique le conseil | — |
| **Jobs** | — | fait défiler les offres |
| **Paramètres** | ligne suivante | la valeur de la ligne |
| **Thème** | applique et enregistre la teinte visée | déplace le curseur |

B est inactif sur trois écrans, et c'est assumé : y coller une action pour
qu'il « serve » créerait des gestes qu'on déclenche par erreur. Un bouton
inerte se remarque moins qu'un bouton qui fait quelque chose d'inattendu.

Deux gestes en plus, uniquement sur Spotify :

| Geste | Effet |
| --- | --- |
| **A maintenu** | piste précédente |
| **C maintenu** | piste suivante |

Maintenir plutôt que taper, parce que l'appui court d'A et de C doit rester la
navigation partout. Les faire changer de piste enfermerait dans Spotify : les
trois boutons seraient pris et seul l'appui long en sortirait. C'est aussi le
geste des autoradios.

Sur le Coach, il n'y a **pas de bouton « ignorer »** : passer à l'écran
suivant *est* l'ignorer. Un bouton qui ne fait rien de plus que partir laisse
surtout se demander ce qu'il a fait.

**Les boutons trient, la molette règle.** C'est ce partage qui rend trois
boutons suffisants pour sept écrans.

## Thèmes

Six palettes : **ambre** (la teinte de TARS), **vert**, **bleu**, **violet**,
**rubis**, **papier**. Le choix se fait **en deux temps** : la molette
déplace un curseur dans la liste sans rien changer, **B applique** la teinte
visée et l'enregistre dans un fichier sur la carte, qui survit donc à une
coupure de courant.

**Rien ne change de couleur avant l'appui.** Le nom en grand annonce la
teinte visée, mais dans l'encre de la teinte *active* : c'est un libellé, pas
un échantillon. La ligne déjà en place porte la mention `ACTIF` — sans elle,
rien ne distinguerait ce qu'on vise de ce qui est appliqué.

Il n'y a donc plus d'aperçu, et c'est le prix assumé : un échantillon ne peut
pas montrer une teinte sans la peindre. On applique pour voir, et on retourne
d'un cran si ça ne plaît pas.

C'est aussi ce qui rend le curseur fluide. Appliquer à chaque cran appelait
`set_palette()`, donc `wipe()`, donc un repaint complet des 240×320 : la
molette traînait d'un demi-tour. Déplacer le curseur ne touche plus que
**32 cellules sur 600**, que le redessin partiel pousse seules.

### La luminosité est la 7e ligne de la même liste

Une palette bien contrastée ne sauve pas un panneau trop sombre en plein
jour : le contraste et la quantité de lumière sont deux réglages différents.
Mais on les cherche au même endroit — quand l'écran se lit mal — donc la
luminosité vit sur l'écran Thème, une ligne sous les six teintes.

Elle ne casse pas la règle du geste : **B agit sur la ligne visée.** Sur une
teinte il l'applique, sur `LUMIERE` il passe au palier suivant. Aucun mode,
aucun second sens à retenir.

```
 > LUMIERE _ [##########]  100%
```

Quatre paliers — **15, 40, 70, 100 %** — plutôt qu'un pourcentage libre : on
ne saurait pas viser une valeur qu'on ne sait pas nommer, alors que quatre
crans couvrent la nuit, la pièce éclairée, la journée et le plein soleil.

**Zéro n'est pas dans la liste.** Un écran éteint par un appui de trop
ressemblerait à une panne, et on en chercherait la cause au lieu du bouton.
L'extinction complète appartient à la veille, qui a une raison de la
déclencher et sait la défaire — `Backlight` garde d'ailleurs son niveau
pendant l'extinction, pour y revenir au réveil.

Le réglage est enregistré dans `awen_backlight.txt`, comme le thème dans
`awen_theme.txt`.

Chaque palette tient en cinq rôles : fond, encre de données, étiquette,
valeur mise en avant, alerte. `DIM` est toujours la teinte principale
assombrie, jamais un gris — un gris casserait l'unité et donnerait l'air d'un
défaut d'affichage.

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
ne sert personne, et le curseur cesse de battre — son clignotement force un
redessin deux fois par seconde pour rien. Le panneau garde son image : au
réveil, le redessin partiel n'envoie que ce qui a réellement changé.

`Backlight` conserve son niveau pendant l'extinction, pour y revenir au
réveil au lieu d'un palier arbitraire.

## Animations

Deux règles de rythme, dans `app.py` :

```python
BOOT_STEP_MS = 300   # apparition d'une ligne d'amorcage
SWEEP_MS     = 14    # une ligne du balayage de transition
```

**L'amorçage** révèle ses lignes une par une, à cadence fixe. La version
précédente n'animait que pendant l'attente du wifi : connexion déjà établie,
les cinq lignes apparaissaient d'un coup et l'écran semblait figé. Le rythme
ne doit rien devoir au réseau — c'est une animation, pas une barre de
progression.

**Le changement d'écran** balaye une ligne lumineuse du haut vers le bas.
Repeindre les 240×320 d'un coup produit un flash noir qui se lit comme un gel
de l'affichage : rien ne bouge, puis tout a changé. Le balayage prend le même
temps mais raconte ce qui se passe.

**Le curseur** bat une fois par seconde (`BLINK_MS = 530`) juste après le
titre, sur tous les écrans. C'est le seul mouvement permanent : sans lui, un
écran qui ne change qu'une fois par minute ne se distingue pas d'un écran
gelé. Sur Paramètres et Thème, un second curseur marque la ligne que le
molette commande — quatre lignes qui se ressemblent ont besoin d'un
repère qui bouge, la surbrillance seule ne suffit pas.

Il ne coûte qu'une cellule par battement grâce au redessin partiel. Ce détail
n'est pas gratuit : `clear()` ne vide **pas** le mémo des jauges, des filets
et du texte agrandi, sinon chaque battement les retracerait deux fois par
seconde et l'écran scintillerait. Seul un changement d'écran purge ce mémo.

Si le rythme ne te convient pas, ces trois constantes sont les seules à
toucher. Monter `SWEEP_MS` à 25 donne une transition nettement plus posée.

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

## Ce qui marche aujourd'hui

Le firmware lit `/api/esp32/summary`, qui renvoie tout **pré-découpé aux
dimensions de l'écran** : titres repliés sur 28 colonnes, accents retirés,
emoji remplacés par un marqueur ASCII. Le serveur connaît la largeur de
l'afficheur, autant qu'il fasse la découpe — c'est du travail en moins pour un
interpréteur MicroPython.

| Écran | État |
| --- | --- |
| Amorçage, Accueil | ✅ |
| Séance | ✅ aperçu des exercices et charges programmées |
| Coach | ✅ conseil, motif, proposition chiffrée, boutons |
| Jobs | ✅ titres des offres du jour |
| Paramètres | ✅ local à l'afficheur |
| Spotify | ⚠️ vide : le bloc `spotify` reste à écrire côté serveur |

### La séance est en lecture seule, et c'est voulu

L'afficheur est posé sur un bureau, pas dans la salle. Quand tu soulèves, ton
téléphone est en main — une série saisie ici n'aurait aucun sens. Ce que tu
veux en rentrant, c'est savoir ce qui t'attend et à quelle charge.

C'est pourquoi `POST /weight` et `/set` n'existent pas. Seul `/advice` est
exposé : trancher un conseil du coach depuis son bureau, ça, c'est naturel.

Et il n'envoie qu'une **intention**, jamais une charge : le serveur relit le
conseil courant et applique sa propre valeur. Un chiffre qui voyagerait sur le
réseau pourrait arriver périmé, et c'est le genre de nombre qu'on ne veut pas
laisser décider ailleurs que dans le moteur de règles.

### Spotify, ce qui reste

Il faut un bloc `spotify{ title, artist, album, position_s, duration_s,
volume, playing, device }` dans le résumé, et un `POST /api/esp32/spotify`
pour lecture / pause / piste / volume.

**Garde le jeton sur le serveur.** Ton `spotify_screen.py` actuel embarque
`CLIENT_ID`, `CLIENT_SECRET` et `REFRESH_TOKEN` sur la carte — c'est
exactement ce qui a fuité par les `.pyc`. Le serveur détient le jeton, gère sa
rotation, et l'afficheur n'est plus qu'une télécommande sans secret.

## Pourquoi le redessin partiel

Repeindre 240×320 coûte une trentaine de millisecondes en MicroPython. À une
image par seconde pour l'horloge, ça clignote et ça rame.

`grid.py` garde une copie de ce qui est réellement à l'écran et ne redessine
que les cellules qui ont changé, en regroupant les voisines de mêmes couleurs
en un seul appel au pilote. Une horloge qui passe de 21:47 à 21:48 coûte une
cellule ; une jauge qui avance d'un pour cent, quelques pixels.

Corollaire à ne pas oublier : au changement d'écran il faut appeler
`g.wipe()`, sinon les cellules identiques d'un écran à l'autre ne seraient
jamais repeintes. `App.go()` s'en charge.

## Caractères

**ASCII uniquement.** La police bitmap n'a ni accents ni flèches : `SÉANCE`
sortirait en `S?ANCE`. Écris en majuscules non accentuées, et utilise `<` `>`
plutôt que `◀` `▶`. `grid.text()` remplace silencieusement tout caractère hors
ASCII par une espace, pour que l'oubli se voie sans casser l'affichage.

Les jauges sont des **rectangles**, jamais des caractères de bloc : dans une
police vectorielle ceux-ci débordent d'une cellule vers le haut et percutent
la ligne au-dessus.
