"""Géométrie des graphiques, calculée côté serveur.

Les gabarits ne font que dessiner : tout le calcul de coordonnées est ici, ce
qui garde le SVG lisible et testable. Les graphiques sont en SVG inline avec un
viewBox — ils s'adaptent donc à la largeur du téléphone sans une ligne de JS ni
la moindre dépendance externe (l'app doit rester utilisable hors ligne).

Conventions de tracé retenues (marques fines, grille discrète, extrémités
arrondies, écart de 2 px entre barres) et couleurs de séries validées pour un
fond sombre — voir stats.FOCUS_COLORS.
"""

W, H = 320.0, 120.0          # viewBox commun
PAD_L, PAD_R, PAD_T, PAD_B = 4.0, 4.0, 10.0, 16.0


def _nice_max(value):
    """Borne haute lisible (1-2-5 × 10ⁿ) pour que la grille tombe juste."""
    if value <= 0:
        return 1.0
    exp = 10 ** (len(str(int(value))) - 1)
    for mult in (1, 1.5, 2, 3, 5, 7.5, 10):
        if value <= mult * exp:
            return mult * exp
    return 10.0 * exp


def line_chart(points, fmt=lambda v: f"{v:g}"):
    """Série temporelle : chemin, aire de remplissage et marqueurs.

    `points` : [(label, valeur), ...] dans l'ordre chronologique.
    """
    if not points:
        return None
    values = [v for _, v in points]
    top = _nice_max(max(values))
    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B
    n = len(points)
    step = plot_w / max(n - 1, 1)

    marks = []
    for i, (label, value) in enumerate(points):
        x = PAD_L + (i * step if n > 1 else plot_w / 2)
        y = PAD_T + plot_h * (1 - value / top)
        marks.append({"x": round(x, 2), "y": round(y, 2),
                      "label": label, "value": value, "text": fmt(value)})

    path = "M" + " L".join(f"{m['x']},{m['y']}" for m in marks)
    area = (f"M{marks[0]['x']},{PAD_T + plot_h} "
            + " ".join(f"L{m['x']},{m['y']}" for m in marks)
            + f" L{marks[-1]['x']},{PAD_T + plot_h} Z")
    return {
        "marks": marks, "path": path, "area": area,
        "top": top, "top_text": fmt(top),
        "baseline": round(PAD_T + plot_h, 2),
        "width": W, "height": H,
    }


def bar_chart(bars, fmt=lambda v: f"{v:g}"):
    """Barres verticales comparables.

    `bars` : [(label, valeur, couleur|None), ...]. Extrémité haute arrondie
    (4 px) et 2 px d'écart entre barres, comme le veut la spécification.
    """
    if not bars:
        return None
    top = _nice_max(max(v for _, v, _ in bars))
    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B
    slot = plot_w / len(bars)
    # 2 px de respiration entre barres, mais largeur plafonnée : avec deux ou
    # trois séries seulement, des barres pleine largeur ressemblent à des blocs
    # de couleur et non à une mesure.
    bar_w = min(30.0, max(6.0, slot - 2.0))

    out = []
    for i, (label, value, color) in enumerate(bars):
        h = plot_h * (value / top) if top else 0
        out.append({
            "x": round(PAD_L + i * slot + (slot - bar_w) / 2, 2),
            "y": round(PAD_T + plot_h - h, 2),
            "w": round(bar_w, 2), "h": round(max(h, 0), 2),
            "label": label, "value": value, "text": fmt(value),
            "color": color,
        })
    return {
        "bars": out, "top": top, "top_text": fmt(top),
        "baseline": round(PAD_T + plot_h, 2),
        "width": W, "height": H,
    }
