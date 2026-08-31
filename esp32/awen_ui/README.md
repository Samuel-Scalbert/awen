# Afficheur Awen — firmware MicroPython

Les sept écrans de [`esp32/mockups.py`](../mockups.py), transposés en
MicroPython pour le pilote `st7789_min.py` d'esp32-desk-display. Grille 30×20,
police 8×8 sur un pas de 16, redessin partiel.

```
theme.py     palettes RGB565 (ambre, phosphore, glacier)
grid.py      grille 30x20 + redessin partiel  <- le coeur
input.py     3 boutons + potentiometre
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

## Câblage

Les boutons se câblent **entre le GPIO et la masse**, sans résistance : le
tirage interne est activé dans `input.py`. Un bouton relâché lit donc 1, un
bouton enfoncé lit 0. Aucune polarité à respecter, un bouton n'a pas de sens.

Le potentiomètre est un diviseur de tension : ses deux **pattes extérieures**
vont sur 3V3 et GND (dans l'ordre que tu veux — l'inverser inverse juste le
sens de rotation), et sa **patte du milieu**, le curseur, sur GPIO 34.

```
        ESP32
   ┌───────────────┐
   │           3V3 ├──────────────┐
   │               │              │  ┌───────────┐
   │        GPIO34 ├──────────────┼──┤ curseur   │  POTENTIOMETRE
   │               │              └──┤ exterieur │
   │           GND ├──────────┬──────┤ exterieur │
   │               │          │      └───────────┘
   │        GPIO26 ├───[A]────┤        A = gauche
   │        GPIO27 ├───[B]────┤        B = milieu
   │        GPIO14 ├───[C]────┘        C = droite
   └───────────────┘
                             les 3 boutons partagent la meme masse
```

L'écran, lui, vient de `tft_setup.py`, déjà « le seul endroit où vivent les
numéros de broches » : CS 5, DC 17, RST 21, rétroéclairage 22, SCK 18,
MOSI 23, SPI 2 à 80 MHz. Ce firmware l'importe au lieu de le redéclarer.

> ### GPIO 34 n'est pas négociable
>
> L'ESP32 a deux convertisseurs analogiques, et **ADC2 cesse de fonctionner
> dès que le wifi est actif**. Un potard câblé sur GPIO 25 ou 26 marcherait
> parfaitement au banc puis renverrait n'importe quoi une fois la carte
> connectée — et des valeurs qui sautent au hasard ne ressemblent en rien à
> « le wifi a pris le convertisseur ».
>
> Les broches **32 à 39** sont sur ADC1. Parmi elles, **34 à 39** sont en
> entrée seule, donc sans tirage interne susceptible de fausser la mesure.
> C'est le bon choix pour un potentiomètre.

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

Le carrousel : **Accueil → Séance → Spotify → Coach → Jobs → Paramètres**,
puis retour au début.

### Ce que fait B, écran par écran

| Écran | Appui court sur B | Le potentiomètre |
| --- | --- | --- |
| **Accueil** | — | — |
| **Séance** | — *(lecture seule)* | fait défiler les exercices |
| **Spotify** | lecture / pause | **le volume** |
| **Coach** | applique le conseil | — |
| **Jobs** | — | fait défiler les offres |
| **Paramètres** | ligne suivante | la valeur de la ligne |

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

**Les boutons trient, le potard règle.** C'est ce partage qui rend trois
boutons suffisants pour six écrans.

## Le rattrapage du potentiomètre

Un potard a une position physique que le firmware ne peut pas changer. C'est
toute la différence avec un encodeur, qui n'envoie que des « +1 » et des
« −1 » sans jamais avoir de position.

Concrètement : tu règles HUMOUR à 75 %, tu passes sur Spotify où le volume est
à 30 %. Le curseur est resté à 75 %. Appliquer sa position telle quelle
collerait le volume à 75 % sans que tu aies rien touché.

La parade est celle des consoles de mixage : **le potard ne prend la main
qu'après avoir traversé la valeur courante.** Tant qu'il ne l'a pas
rattrapée, l'écran affiche vers où tourner :

```
TOURNE >  30%
```

Sans ce repère, on tourne, rien ne bouge, et on croit le potard cassé.

`App.rearm_pot()` réarme le rattrapage à chaque changement d'écran — et aussi
quand on change de ligne dans les Paramètres, puisque la valeur cible change.

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
