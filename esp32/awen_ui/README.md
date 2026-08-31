# Afficheur Awen — firmware MicroPython

Les sept écrans de [`esp32/mockups.py`](../mockups.py), transposés en
MicroPython. Grille 30×20, police bitmap 8×16, redessin partiel.

```
theme.py     palettes RGB565 (ambre, phosphore, glacier)
grid.py      grille 30x20 + redessin partiel  <- le coeur
input.py     3 boutons + encodeur rotatif
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
| Encodeur CLK | 26 | valeurs continues |
| Encodeur DT | 27 | |

Écran (broches SPI courantes, **à vérifier contre ta carte**) : SCK 14,
MOSI 13, DC 2, CS 15, RST 4, rétroéclairage 21.

## Navigation

Six écrans en carrousel : **Accueil → Séance → Coach → Jobs → Paramètres →
Discussion**, puis retour. L'amorçage ne s'affiche qu'au démarrage.

L'encodeur agit **dans** l'écran courant, jamais entre les écrans :

| Écran | Un cran de molette |
| --- | --- |
| Séance | charge ±2,5 kg (le plus petit disque en salle) |
| Paramètres | valeur ±5 % |
| Jobs | offre suivante / précédente |

C'est le partage qui rend trois boutons suffisants : les boutons trient, la
molette règle. Sans elle, ajuster une charge demanderait une douzaine d'appuis.

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

Le firmware lit `/api/esp32/summary`. Cet endpoint existe déjà mais ne renvoie
pas encore tout ce que les écrans savent afficher. **Rien ne plante** — chaque
champ absent retombe sur une valeur neutre — mais trois écrans restent
partiellement vides.

| Écran | État |
| --- | --- |
| Amorçage, Accueil | ✅ complet |
| Coach | ✅ le conseil s'affiche ; il manque `subject`, `from_kg`, `to_kg` pour la proposition chiffrée |
| Jobs | ⚠️ le nombre s'affiche ; il manque `jobs.offers[]` pour les titres |
| Séance | ⚠️ vide : il manque tout le bloc `gym.exercise` |
| Discussion | ⏸ en attente de la couche vocale |

Champs à ajouter côté serveur dans `app/routes/esp32.py` :

```
gym.session_no, gym.done_pct, gym.left
gym.exercise{ name, index, count, set, sets, weight_kg, reps, target }
jobs.offers[]{ title, org }
coach.subject, coach.from_kg, coach.to_kg, coach.why, coach.pe_id
rest_s, rest_pct
```

Les trois actions (`commit_weight`, `log_set`, `apply_advice`) appellent
`POST /api/esp32/weight`, `/set` et `/advice`, **qui n'existent pas encore**.
En leur absence la requête échoue proprement et l'écran ne se rafraîchit pas :
aucune donnée n'est perdue, mais le bouton semble sans effet.

## Pourquoi le redessin partiel

Repeindre 240×320 coûte une trentaine de millisecondes en MicroPython. À une
image par seconde pour l'horloge, ça clignote et ça rame.

`grid.py` garde une copie de ce qui est réellement à l'écran et ne redessine
que les cellules qui ont changé, en regroupant les voisines de mêmes couleurs
en un seul appel au pilote. Une horloge qui passe de 21:47 à 21:48 coûte une
cellule ; un chronomètre de repos, cinq. C'est toute la différence entre un
afficheur fluide et un afficheur poussif.

Corollaire à ne pas oublier : au changement d'écran il faut appeler
`g.wipe()`, sinon les cellules identiques d'un écran à l'autre ne seraient
jamais repeintes. `App.go()` s'en charge.

## Caractères

**ASCII uniquement.** La police bitmap n'a ni accents ni flèches : `SÉANCE`
sortirait en `S?ANCE`. Écris en majuscules non accentuées, et utilise `<` `>`
plutôt que `◀` `▶`. `grid.text()` remplace silencieusement tout caractère hors
ASCII par une espace, pour que l'oubli se voie sans casser l'affichage.
