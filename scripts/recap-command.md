---
description: Recapituler la session en cours et pousser le recap vers Awen
---

Ecris le recap de cette session de travail, puis pousse-le vers Awen.

1. Regarde l'etat du depot : `git status --porcelain`, `git log -1 --oneline`,
   `git diff --stat HEAD`, et la branche courante.
2. Ecris `.claude/recap/recap.json` (cree le dossier si besoin) avec exactement
   ces cles, en francais **sans accents** (le JSON est relu par un afficheur
   dont la police n'en a pas) :

```json
{
  "project": "<nom du dossier racine du depot>",
  "branch": "<branche courante>",
  "stopped_at": "une phrase : ou on s'est arrete",
  "done": ["ce qui a ete fait dans cette session, 3 elements max"],
  "next": ["les prochaines choses a faire, a l'imperatif, 3 elements max"],
  "blockers": ["ce qui bloque ou reste incertain, 2 max, [] si rien"],
  "dirty": <nombre de fichiers modifies non commites>,
  "last_commit": "<hash court> <sujet>",
  "host": "<nom de la machine>"
}
```

   Chaque element de liste fait moins de 90 caracteres : il s'affiche sur un
   ecran de telephone, tronque a 34 colonnes.

3. Pousse-le : `powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\User\awen\scripts\dev-recap.ps1 -Mode push -Verbose`

Appuie-toi sur ce qu'on a reellement fait dans cette conversation, pas
seulement sur le diff : « next » doit refleter ce qu'on s'etait dit de faire
ensuite. N'invente rien — une liste vide vaut mieux qu'une tache devinee.
