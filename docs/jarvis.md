# Jarvis — l'assistant local d'Awen

> Document de conception. Écrit le 16 septembre 2026, avant toute installation.
> TARS donne le visage et le ton sur l'écran de 30 colonnes. Jarvis donne la
> voix, le raisonnement, et un poste de commande en plein écran.

## Ce qu'on construit, et ce qu'on ne construit pas

Awen sait déjà des choses : les séances faites, les charges, les absences, les
recettes et leurs macros, le calendrier Samsung, la veille emploi du matin.
Tout est là, mais il faut **aller le chercher** — ouvrir la bonne page, lire le
bon tableau.

Jarvis est la couche qui répond à la place de l'interface :

> — *Je fais quoi aujourd'hui ?*
> — *Il me reste combien de protéines cette semaine ?*
> — *Résume-moi la veille emploi de ce matin.*
> — *Ajoute « appeler le dentiste » à ma liste.*

**Ce n'est pas un robot conversationnel de plus.** Un modèle qui ne sait rien
de toi ne vaut pas le GPU qu'il consomme : il y en a déjà un meilleur dans ton
navigateur. La valeur est entièrement dans **l'accès aux données d'Awen**.
C'est pour ça que l'étape des outils passe avant l'étape de la voix, alors que
l'instinct pousse à l'inverse.

**Hors périmètre :** agir sur l'extérieur (envoyer un mail, acheter quelque
chose), et tout ce qui demande d'exposer le serveur sur Internet.

## L'état du terrain, mesuré le 16 septembre 2026

| | Constat | Conséquence |
| --- | --- | --- |
| **Carte graphique** | RTX 3070 (GA104) présente, mais pilotée par **nouveau** | Pas de CUDA. Aucune inférence GPU possible aujourd'hui. |
| **Dépôts APT** | Debian 13 trixie, `main non-free-firmware` seulement | Il faut ajouter `contrib non-free` pour `nvidia-driver`. |
| **Mémoire vive** | **7,7 Go au total**, 6,8 libres | La vraie contrainte. Plus serrée que la VRAM. |
| **Processeur** | 12 fils d'exécution | Suffisant pour la synthèse vocale. |
| **Disque** | 210 Go libres sur le NVMe | Large, même avec plusieurs modèles. |
| **Déjà en service** | Conteneurs `awen` et `film_finder-web-1` | **Un redémarrage les coupe tous les deux.** |
| **Rien d'installé** | Ni Ollama, ni ffmpeg, ni whisper, ni piper | Page blanche. |
| **Entrées / sorties** | Une enceinte filaire sur la prise AUX. **Pas de micro.** | Jarvis pourra parler bien avant de pouvoir écouter. |

## L'architecture visée

```
   navigateur (HUD plein écran)              ESP32 (TARS)
     │  chat clavier                              │  texte, 30x20
     │  pavé numérique                            │
     │  lecture audio ──► enceinte AUX            │
     ▼                                            ▼
   ┌──────────────────────────────────────────────────┐
   │                Awen (Flask, Docker)              │
   │                                                  │
   │   /jarvis   ──►  services/jarvis.py              │
   │   /todos    ──►  models/todo.py                  │
   │                      │                           │
   │                      ├─► outils ─► progression, attendance,
   │                      │             coach, meals, calendar,
   │                      │             job_watch, stats, todo
   │                      ▼                           │
   └──────────────────────┼───────────────────────────┘
                          │ HTTP, réseau local
             ┌────────────┴────────────┐
             │   Ollama (hôte, GPU)    │
             │   Qwen3 8B Q4_K_M       │
             └────────────┬────────────┘
                          │
            Piper (CPU) ──┴── parole ──► WAV ──► navigateur
            faster-whisper (GPU) ─ écoute ─ plus tard, quand micro
```

**Ollama tourne sur l'hôte, pas dans un conteneur.** Passer le GPU à Docker
demande `nvidia-container-toolkit` et alourdit le `docker-compose.yml` d'Awen
pour un gain nul : Ollama expose déjà une API HTTP sur `127.0.0.1:11434`, et le
conteneur Awen peut l'appeler. Une dépendance de moins à déboguer.

## Le budget mémoire, qui décide de tout

8 Go de VRAM, et deux modèles qui voudraient y tenir en même temps :

| Ce qui charge | VRAM | Remarque |
| --- | --- | --- |
| Qwen3 8B en Q4_K_M | ~5,5 Go | Laisse de la place pour le contexte. |
| faster-whisper `small` en int8 | ~1 Go | Plus tard, quand il y aura un micro. |
| Contexte et tampons | ~1 Go | |
| **Total** | **~7,5 Go** | Ça tient, sans marge. |

Deux règles qui en découlent :

- **Ne pas viser plus gros.** Un modèle de 9B en Q4 occupe ~6,6 Go : il ne
  laisse plus de place à Whisper. Si les deux doivent cohabiter, 8B est le
  plafond.
- **`keep_alive` explicite.** Par défaut Ollama décharge le modèle après cinq
  minutes d'inactivité, et la question suivante attend le rechargement depuis
  le disque. Sur une machine à 7,7 Go de RAM, le garder chargé en permanence
  est possible mais laisse peu d'air aux deux conteneurs. **À mesurer avant de
  trancher.**

Piper ne figure pas dans ce tableau : il tourne sur le processeur et ne prend
pas un octet de VRAM. C'est précisément pourquoi il est retenu.

---

# L'interface — le poste de commande

L'écran de référence : fond noir, cyan, capitales espacées en chasse fixe,
crochets d'angle, un globe de points qui tourne au centre, une barre d'état en
haut, les commandes en bas.

```
 ┌ MENU ┐                ╔══════════════════════════╗           ● connecté
 │      │                ║  ◆ LOCAL_TIME            ║
 │ SEANCE_DU_JOUR        ║ CPU   17:39:12    RAM    ║
 │ PROGRESSION           ║ 14%               48%    ║
 │ REPAS / MACROS        ║ SYS_CLOCK 16/09  ONLINE  ║
 │ LISTE_COURSES         ╚══════════════════════════╝
 │ CALENDRIER
 │ TACHES                          . ·· ˙ · .
 │ VEILLE_EMPLOI                 · ˙  ___  ˙ ·
 │ SPOTIFY                      ·  ˙/     \˙  ·
 │ ECRAN_ESP32                  ·  |  ●●●  |  ·
 │ ETAT_SERVEUR                  · ˙\ ___ /˙ ·
 │ PARAMETRES                      ˙ · ·· ˙
 │
 │ VERSION 0.1                   ( 🎤 )  ( ■ )
 └──────┘                        en écoute...
```

## Comment on dessine le globe

**Un `<canvas>` en 2D, sans bibliothèque.** Environ 600 points répartis sur une
sphère, projetés en perspective, reliés à leurs voisins proches.

Le détail qui fait la différence entre fluide et saccadé : **les liaisons se
calculent une seule fois, au chargement**. La sphère est rigide — deux points
voisins le restent quelle que soit la rotation. Recalculer les distances à
chaque image, c'est 360 000 comparaisons soixante fois par seconde pour un
résultat qui ne change jamais. On calcule la liste des paires au démarrage, et
chaque image ne fait plus que tourner, projeter et tracer.

Pas de Three.js : une dépendance de 600 Ko pour un nuage de points qu'on écrit
en cent lignes, et qui doit de toute façon rester lisible dans six mois.

## La barre d'état

`services/host.py` fournit déjà la mémoire, le disque, la charge et les
conteneurs, via le fichier déposé par `scripts/host-status.sh`. Il manque le
pourcentage processeur : **une ligne à ajouter au script**, pas un nouveau
mécanisme.

La règle de fraîcheur existante s'applique telle quelle : au-delà de cinq
minutes, `host.py` renvoie `None` plutôt qu'un relevé périmé. **Le HUD affiche
alors `--%`, jamais le dernier chiffre connu.** Un indicateur qui ment est pire
qu'un indicateur vide — c'est déjà la philosophie du module, on ne la casse pas
pour faire joli.

Le voyant « connecté » en haut à droite dit une seule chose : **Ollama
répond-il ?** Pas « le serveur est allumé » — ça, la page chargée le prouve
déjà.

## Le menu

Il liste **nos modules, pas ceux de l'image**. « ACTIVER LA VISION », « GPU
BOOST », « ANTIVIRUS » sont les entrées d'un autre projet ; chez nous elles ne
mèneraient nulle part.

Un bouton qui ne fait rien est pire que pas de bouton : il coûte un clic, une
déception, et il apprend à se méfier du reste du menu.

Les entrées réelles : séance du jour · progression · repas et macros · liste de
courses · calendrier · **tâches** · veille emploi · Spotify · écran ESP32 ·
état du serveur · paramètres. Toutes pointent vers des pages qui existent
déjà — le HUD est une porte d'entrée, pas une réécriture de l'application.

---

# Parler à Jarvis sans micro

## 1. Le chat

Un champ de saisie en bas du HUD, l'historique au-dessus. C'est le chemin
principal, et le seul qui permette une question longue.

Deux réponses sont demandées au modèle à chaque tour :

- **la réponse complète**, affichée dans le HUD et lue à voix haute ;
- **une phrase de 60 caractères maximum**, pour l'ESP32.

Trente colonnes ne contiennent pas un paragraphe. C'est une contrainte de
consigne, pas de code : on la demande au modèle, on ne tronque pas après coup —
une phrase coupée au milieu est illisible, une phrase courte ne l'est pas.

## 2. Le pavé numérique

Un pavé USB à part, dont les touches envoient les phrases les plus fréquentes.
Dix-sept touches, donc dix-sept phrases, en une frappe.

Une proposition de départ, à remanier à l'usage :

| Touche | Phrase envoyée |
| --- | --- |
| `7` `8` `9` | *Je fais quoi aujourd'hui ?* · *Montre ma progression* · *Conseil du coach* |
| `4` `5` `6` | *Mes macros du jour* · *Qu'est-ce que je mange ce soir ?* · *Liste de courses* |
| `1` `2` `3` | *Mes prochains rendez-vous* · *Mes tâches en cours* · *Veille emploi du jour* |
| `0` | *Tâche suivante* |
| `.` | *Marque la tâche comme faite* |
| `+` | *Répète* |
| `−` | *Stop* (coupe la lecture en cours) |
| `Entrée` | *Développe ta réponse* |
| `*` `/` | Libres — à remplir après une semaine d'usage réel |

### Comment c'est branché, et le piège à connaître

**Au début : rien à installer.** La page HUD écoute les touches du navigateur.
`Numpad7`, `NumpadAdd`, `NumpadEnter` sont des codes distincts des chiffres du
haut du clavier : on les reconnaît sans ambiguïté.

**Le piège :** le navigateur ne sait pas *quel clavier* a produit la touche. Si
tu tapes `7` dans le chat, c'est le même événement que la touche `7` du pavé.
La règle qui règle le problème en une ligne : **les raccourcis ne se
déclenchent que si le champ de saisie n'a pas le focus.** Le chat reste un
chat, le pavé reste un pavé.

**Plus tard, si tu veux que ça marche hors du navigateur :** un script
AutoHotkey sur le PC qui appelle l'API d'Awen. Cela permet d'interroger Jarvis
depuis n'importe quelle fenêtre — mais distinguer deux claviers physiques sous
Windows demande un pilote d'interception. À ne faire que si le besoin se
présente vraiment.

---

# La voix qui sort

Tu as une enceinte, pas de micro. **Jarvis parlera donc bien avant d'écouter**,
et c'est une bonne chose : entendre la réponse change l'usage bien plus que
dicter la question.

**Piper**, sur le processeur du serveur, avec une voix française. Il démarre
instantanément, ne consomme pas de VRAM, et il en existe plusieurs timbres à
essayer.

**Le son sort par le navigateur, pas par le serveur.** Le serveur fabrique le
WAV, Awen le sert, la page le joue. L'alternative — faire jouer le son au
serveur lui-même — obligerait à donner à un conteneur Docker l'accès à la carte
son de l'hôte : un montage fragile, qui casse à chaque mise à jour, pour le
même résultat audible.

**Conséquence pratique : branche l'enceinte sur la machine où tu ouvres le
HUD.** Si c'est ton PC principal, l'enceinte va sur son AUX et tout fonctionne
sans un réglage de plus.

Deux détails qui comptent à l'usage :

- **Un bouton « stop » qui coupe vraiment.** Une réponse longue lue en entier
  alors qu'on a compris à la troisième seconde, c'est l'irritation qui fait
  abandonner un assistant. La touche `−` du pavé y est réservée.
- **Les navigateurs refusent de jouer un son avant la première interaction.**
  Comme on arrive toujours par un clic ou une frappe, ça ne se verra pas — mais
  c'est la cause classique du « pourquoi il ne parle pas ».

---

# La liste de tâches

Un vrai module d'Awen, pas un bout de la page Jarvis. Il se remplit depuis le
HUD, depuis le pavé, depuis Jarvis, et se consulte sur l'ESP32.

**Le modèle**, volontairement minimal :

| Champ | Rôle |
| --- | --- |
| `texte` | La tâche. |
| `fait` | Fait ou non. |
| `cree_le`, `fait_le` | Pour savoir ce qui traîne. |
| `echeance` | Optionnelle. Sans elle, une liste devient un cimetière. |
| `source` | `web`, `jarvis` ou `pave` — pour voir par où ça rentre réellement. |

**Sur l'ESP32 :** les trois prochaines tâches, une par ligne, tronquées à 30
colonnes. Pas de rayure, pas de coche : l'écran affiche, il ne gère pas.

## Le seul endroit où Jarvis a le droit d'écrire

Le reste du projet est en **lecture seule** : le jour où Jarvis peut
enregistrer une séance, il peut aussi en inventer une, et une base
d'entraînement faussée ne se répare pas — on ne sait plus quelle ligne est
vraie.

**La liste de tâches est l'exception assumée.** Une tâche inventée se voit
immédiatement et s'efface en un clic. Le risque est nul, l'usage est quotidien.

Trois outils, et seulement trois :

```
taches_en_cours()          lecture
ajouter_tache(texte)       écriture — la seule qui crée
terminer_tache(id)         écriture — réversible
```

Pas de `supprimer_tache`. Terminer suffit, et garde une trace.

---

# Les étapes

Chacune est utilisable seule. On peut s'arrêter à n'importe laquelle.

| | Étape | Ce que ça donne | Dépend de |
| --- | --- | --- | --- |
| **0** | Pilote NVIDIA, accès GPU | `nvidia-smi` répond. Un redémarrage. | — |
| **1** | Ollama + Qwen3 8B | Tu discutes avec ton serveur en ligne de commande. | 0 |
| **2** | **Les outils** + banc d'essai | C'est ici que ça devient Jarvis. | 1 |
| **3** | **La liste de tâches** | Utile même sans Jarvis. Et c'est le chemin d'écriture. | — |
| **4** | **Le HUD + le chat** | Le poste de commande, utilisable au clavier. | 2, 3 |
| **5** | **Le pavé numérique** | Dix-sept phrases en une frappe. | 4 |
| **6** | **La parole** (Piper → enceinte) | Il répond à voix haute. | 4 |
| **7** | L'écoute (Whisper) | Quand tu auras un micro. | 0, 6 |
| **8** | Micro et haut-parleur sur l'ESP32 | L'objet devient autonome. Achat. | 7 |

**Les étapes 3 et 4 ne dépendent pas du GPU.** Si l'étape 0 traîne — Secure
Boot, moment mal choisi pour redémarrer — la liste de tâches et le HUD peuvent
être construits et utilisés en attendant. Le HUD sans cerveau reste un tableau
de bord qui marche.

**Comment on saura que l'étape 2 est réussie :** un banc d'essai d'une
quinzaine de questions dont on connaît déjà la réponse, rejouable à chaque
changement de modèle. C'est lui qui dira si Qwen3 8B suffit — pas une
impression après trois essais.

---

# Ce qui peut casser, et ce qu'on fera

| Risque | Parade |
| --- | --- |
| Le redémarrage de l'étape 0 coupe le site de films | Choisir le moment, prévenir. Les deux conteneurs redémarrent seuls. |
| Secure Boot bloque le module NVIDIA | Le désactiver dans le BIOS, ou signer le module. **À vérifier avant de commencer** : le symptôme trompe, `nvidia-smi` dit « pilote introuvable » alors que le paquet est installé. |
| 7,7 Go de RAM, deux conteneurs et Ollama | Mesurer avec `free -h` sous charge. Si ça serre, décharger le modèle entre les questions. |
| Le modèle 8B enchaîne mal plusieurs outils | Le risque principal du choix « local ». Le banc d'essai le dira. Repli : bascule vers une API pour les questions difficiles. |
| Le modèle invente un chiffre | Tout nombre passe par un outil, jamais par le modèle. Afficher la source dans la réponse. |
| Le pavé et le chat se marchent dessus | Les raccourcis ne se déclenchent que hors du champ de saisie. |
| Le HUD affiche un relevé périmé | `host.py` renvoie `None` au-delà de 5 min ; le HUD montre `--%`. |
| SQLite et un seul processus écrivain | Jarvis n'écrit que dans `todos`, une ligne à la fois. |

# Les choix, et pourquoi

**Ollama plutôt que llama.cpp nu ou vLLM.** llama.cpp demande de gérer
soi-même le chargement et l'API ; vLLM est fait pour servir plusieurs
utilisateurs en parallèle et suppose beaucoup plus de VRAM. Ici il y a un seul
utilisateur et 8 Go.

**Local plutôt que l'API.** Décision prise : les données restent à la maison,
ça ne coûte rien à l'usage, ça marche sans Internet. Le prix à payer est un
modèle moins fin quand il faut enchaîner plusieurs outils. La bascule reste
possible plus tard sans rien jeter : la couche d'outils de l'étape 2 est
indépendante du cerveau qui l'appelle.

**Des outils, pas une base vectorielle.** Tes données sont petites,
structurées, déjà interrogeables en SQL. Un RAG ajouterait un index à tenir à
jour et répondrait de façon approximative à des questions qui ont une réponse
exacte. « Combien de séances ratées en août » n'est pas une question de
similarité sémantique, c'est un `COUNT`.

**Les outils avant la voix.** Un assistant vocal sans données, c'est une
enceinte connectée. Un assistant texte qui connaît tout de toi, c'est déjà
Jarvis.

**Le HUD est une façade, pas une application.** Il rassemble et met en scène ce
qui existe. Le jour où il faut choisir entre une animation de plus et une
donnée juste, c'est la donnée qui gagne.
