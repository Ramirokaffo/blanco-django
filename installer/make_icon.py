#!/usr/bin/env python
"""
Génère l'icône Windows de l'application (installer/blanco.ico).

Le script est versionné pour que l'icône reste reproductible. Pour remplacer
ce visuel par le vrai logo de l'enseigne, déposez simplement un blanco.ico
(multi-tailles 16→256) à côté de ce fichier : la compilation le reprendra tel
quel, sans exécuter ce script.

    python installer/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

#: Couleur primaire de l'interface (core/static/css : --primary-color).
ORANGE = (255, 140, 0, 255)
ORANGE_DARK = (204, 112, 0, 255)
WHITE = (255, 255, 255, 255)

#: Tailles embarquées dans le .ico (Windows pioche selon le contexte).
SIZES = [16, 24, 32, 48, 64, 128, 256]

CANVAS = 1024

FONT_CANDIDATES = [
    "C:/Windows/Fonts/segoeuib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def _load_font(size: int):
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def build_image() -> Image.Image:
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Carré arrondi façon icône d'application, avec un léger dégradé vertical.
    radius = int(CANVAS * 0.22)
    draw.rounded_rectangle([0, 0, CANVAS - 1, CANVAS - 1], radius=radius, fill=ORANGE_DARK)
    draw.rounded_rectangle(
        [0, 0, CANVAS - 1, int(CANVAS * 0.88)], radius=radius, fill=ORANGE
    )

    # Monogramme centré.
    font = _load_font(int(CANVAS * 0.62))
    left, top, right, bottom = draw.textbbox((0, 0), "B", font=font)
    draw.text(
        ((CANVAS - (right - left)) / 2 - left, (CANVAS - (bottom - top)) / 2 - top),
        "B",
        font=font,
        fill=WHITE,
    )
    return image


def main():
    target = Path(__file__).resolve().parent / "blanco.ico"
    image = build_image()
    image.save(target, format="ICO", sizes=[(s, s) for s in SIZES])
    # PNG utile pour l'installeur et la documentation.
    image.resize((256, 256), Image.LANCZOS).save(target.with_suffix(".png"))
    print(f"Icône écrite : {target}")


if __name__ == "__main__":
    main()
