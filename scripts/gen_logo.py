"""Genere esp32/awen_ui/logo.py : les images du logo Awen en rotation.

Le trace est fait ICI, une fois, avec de vrais sinus. L'ESP32 ne recoit que
le resultat : une liste de pixels a peindre. Calculer une spirale sur la
carte huit fois par seconde couterait cher pour un dessin qui ne change
jamais.

    python scripts/gen_logo.py
"""
import io
import math

SIZE = 16              # deux cellules de la grille, une ligne de haut
CENTRE = (SIZE - 1) / 2.0
NIVEAUX = 8            # autant de teintes que theme.LOGO_RING
PHASES = 8
BRAS = 2
TOURS = 0.55
LARGEUR = 2.4
R_MIN, R_MAX = 1.0, 7.0

A = TOURS * 2 * math.pi / (R_MAX - R_MIN)


def image(phase):
    """Renvoie SIZE*SIZE niveaux, 0 = fond."""
    # UN DEMI-TOUR SUFFIT AVEC DEUX BRAS : la figure se superpose a
    # elle-meme tous les 180 degres. Etaler les huit images sur un tour
    # complet en aurait fait quatre paires identiques, et la rotation aurait
    # saute une image sur deux.
    dec = 2 * math.pi * phase / (PHASES * BRAS)
    out = []
    for y in range(SIZE):
        for x in range(SIZE):
            dx, dy = x - CENTRE, y - CENTRE
            r = math.hypot(dx, dy)
            if r > R_MAX or r < 0.6:
                out.append(0)
                continue
            th = math.atan2(dy, dx)
            best = 0
            for b in range(BRAS):
                phi = A * (r - R_MIN) + dec + 2 * math.pi * b / BRAS
                d = (th - phi + math.pi) % (2 * math.pi) - math.pi
                # L'ecart angulaire est multiplie par le rayon : sans ca le
                # bras s'epaissirait vers l'exterieur et se pincerait au
                # centre. Le plancher a 1.6 evite qu'il n'explose au coeur.
                if abs(d) * max(r, 1.6) <= LARGEUR:
                    t = (r - R_MIN) / (R_MAX - R_MIN)
                    best = max(best, NIVEAUX - int(t * (NIVEAUX - 1)))
            out.append(best)
    return out


def main():
    frames = [image(p) for p in range(PHASES)]

    # On n'emet QUE les pixels du bras. Le fond est peint d'un bloc sur la
    # carte, et parcourir 256 cases pour en trouver soixante serait du
    # gaspillage a chaque image.
    paires = []
    for f in frames:
        duo = bytearray()
        for i, v in enumerate(f):
            if v:
                duo.append(i)
                duo.append(v)
        paires.append(bytes(duo))

    distinctes = len(set(paires))
    if distinctes != PHASES:
        raise SystemExit(
            "{} images sur {} seulement sont distinctes : la rotation "
            "sauterait.".format(distinctes, PHASES))

    CH = " .:-=+*#@"
    apercu = []
    for p in (0, 2, 4):
        apercu.append("Phase {} :".format(p))
        for y in range(SIZE):
            apercu.append("    " + "".join(
                CH[frames[p][y * SIZE + x]] for x in range(SIZE)))
        apercu.append("")

    tete = [
        "Le logo Awen, precalcule image par image.",
        "",
        "GENERE PAR scripts/gen_logo.py — NE PAS EDITER A LA MAIN.",
        "",
        "Chaque image est une suite de paires (position, niveau) : seuls les",
        "pixels du bras y figurent, le fond etant peint d'un bloc. Le niveau",
        "indexe theme.LOGO_RING, de 1 (bout du bras, clair) a 8 (coeur,",
        "sombre).",
        "",
        "Deux bras sur {:.2f} tour dans un carre de {} px, soit deux cellules".format(TOURS, SIZE),
        "de la grille. A cette taille, une spirale plus serree se remplit et",
        "devient une tache : c'est cette contrainte qui a fixe ces valeurs,",
        "pas un gout pour les demi-tours.",
        "",
    ] + apercu

    src = ['"""' + tete[0]] + tete[1:] + ['"""', ""]
    src += ["SIZE = {}".format(SIZE),
            "PHASES = {}".format(PHASES),
            "",
            "FRAMES = ("]
    for duo in paires:
        src.append("    {!r},".format(duo))
    src += [")", ""]

    io.open("esp32/awen_ui/logo.py", "w", encoding="utf-8",
            newline="\n").write("\n".join(src))

    print("logo.py : {} images distinctes, {} octets".format(
        PHASES, sum(len(d) for d in paires)))
    for l in apercu:
        print(l)


if __name__ == "__main__":
    main()
