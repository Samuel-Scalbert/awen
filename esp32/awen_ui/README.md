# Afficheur Awen — firmware MicroPython

Les sept écrans de [`esp32/mockups.py`](../mockups.py), transposés en
MicroPython. Grille 30×20, police bitmap 8×16, redessin partiel.

```
theme.py     palettes RGB565 (ambre, phosphore, glacier)
grid.py      grille 30x20 + redessin partiel  <- le coeur
input.py     3 boutons + potentiometre
screens.py   les 7 ecrans
app.py       navigation, reseau, boucle principale
main.py      cablage materiel  <- le seul fichier a adapter
```

## Ce que le firmware suppose

Écrit contre **[russhughes/st7789_mpy](https://github.com/russhughes/st7789_mpy)**
et sa police `vga1_8x16`, qui donne exactement 30 colonnes sur 20 lignes en
240×320. `vga1_bold_16x32` sert à l'heure de l'écran de veille.

`grid.py` n'appelle que **deux** méthodes du pilote :

```python
display.text(font, texte, x, y, couleur, fond)
display.fill_rect(x, y, largeur, hauteur, couleur)
```

Pour un autre pilote, adapter ces deux appels suffit.

## Câblage

Boutons entre le GPIO et la masse, sans résistance externe — le tirage interne
est activé dans `input.py`.

| Entrée | GPIO | Rôle |
| --- | --- | --- |
| Bouton A | 32 | écran précédent · maintenu, défile |
| Bouton B | 33 | valider · **appui long** = retour à l'accueil |
| Bouton C | 25 | écran suivant · maintenu, défile |
| Potentiomètre | **34** | valeurs (extrémités sur 3V3 et GND, curseur sur 34) |

> **GPIO 34 n'est pas négociable.** L'ESP32 a deux convertisseurs analogiques
> et **ADC2 cesse de fonctionner dès que le wifi est actif**. Un potard câblé
> sur GPIO 25 ou 26 lirait n'importe quoi une fois connecté — et le symptôme
> (des valeurs qui sautent au hasard) ne ressemble pas du tout à sa cause.
> Les broches 32–39 sont sur ADC1 ; 34–39 sont en entrée seule, donc sans
> tirage interne parasite.

Écran (broches SPI courantes, **à vérifier contre ta carte**) : SCK 14,
MOSI 13, DC 2, CS 15, RST 4, rétroéclairage 21.

## Navigation

Six écrans en carrousel : **Accueil → Séance → Spotify → Coach → Jobs →
Paramètres**, puis retour. L'amorçage ne s'affiche qu'au démarrage.

Le potentiomètre agit **dans** l'écran courant, jamais entre les écrans :

| Écran | Le potard règle |
| --- | --- |
| Spotify | le volume — son usage le plus naturel |
| Séance | la charge, de −10 à +10 kg par pas de 2,5 kg |
| Paramètres | la valeur sélectionnée, de 0 à 100 % |
| Jobs | l'offre affichée |

**Les boutons trient, le potard règle.** C'est ce partage qui rend trois
boutons suffisants.

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

```bash
cp awen_config.example.py awen_config.py   # wifi + cle d'API
mpremote cp theme.py grid.py input.py screens.py app.py main.py \
            awen_config.py :
mpremote reset
```

`awen_config.py` contient un mot de passe wifi et la clé d'API : il est dans
le `.gitignore`, ne le versionne jamais. `ESP32_API_KEY` doit correspondre
exactement au `.env` du serveur.

## Ce qui marche aujourd'hui, et ce qui attend le serveur

Le firmware lit `/api/esp32/summary`. Cet endpoint existe mais ne renvoie pas
encore tout ce que les écrans savent afficher. **Rien ne plante** — chaque
champ absent retombe sur une valeur neutre — mais trois écrans restent
partiellement vides.

| Écran | État |
| --- | --- |
| Amorçage, Accueil | ✅ complet |
| Coach | ✅ le conseil s'affiche ; manque la proposition chiffrée |
| Jobs | ⚠️ le nombre s'affiche ; manquent les titres |
| Séance | ⚠️ vide : il manque tout le bloc `gym.exercise` |
| Spotify | ⚠️ vide : il manque le bloc `spotify` |

Champs à ajouter côté serveur dans `app/routes/esp32.py` :

```
gym.session_no, gym.done_pct, gym.left
gym.exercise{ name, index, count, set, sets, weight_kg, reps, target }
jobs.offers[]{ title, org }
coach.subject, coach.from_kg, coach.to_kg, coach.why, coach.pe_id
spotify{ title, artist, album, position_s, duration_s, volume,
         playing, device }
rest_s, rest_pct
```

Les actions appellent `POST /api/esp32/weight`, `/set`, `/advice` et
`/spotify`, **qui n'existent pas encore**. En leur absence la requête échoue
proprement et l'écran ne se rafraîchit pas : aucune donnée n'est perdue, mais
le bouton semble sans effet.

**Spotify : garde le jeton sur le serveur.** L'ESP32 ne doit pas parler
directement à l'API Spotify — il faudrait y stocker un jeton de
rafraîchissement et gérer sa rotation sur un appareil sans stockage sûr. Le
serveur détient le jeton et expose `/api/esp32/spotify` ; l'afficheur n'est
qu'une télécommande.

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
