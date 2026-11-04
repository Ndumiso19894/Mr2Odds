"""Rebuild launcher, splash and web logos from the supplied Mr 2 Odds artwork.

Run: python android/tools/make_logo.py (requires Pillow).
Adaptive foreground artwork stays inside Android's central 66/108 safe zone.
"""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'design/mr-2-odds-logo.png'
RES = ROOT / 'app/src/main/res'
WWW = ROOT / 'app/src/main/assets/www'


def main():
    original = Image.open(SRC).convert('RGB')
    if original.size != (2048, 2048):
        raise ValueError('Expected the original 2048×2048 logo')
    # The supplied square includes generous margins. Keep the complete circular emblem,
    # with a little background around it, so the face and lettering remain legible.
    emblem = original.crop((240, 240, 1808, 1808))
    emblem.resize((512, 512), Image.Resampling.LANCZOS).save(WWW / 'logo.png', optimize=True)
    emblem.resize((512, 512), Image.Resampling.LANCZOS).save(RES / 'drawable-nodpi/splash_logo.png', optimize=True)
    for density, size in [('mdpi', 108), ('hdpi', 162), ('xhdpi', 216), ('xxhdpi', 324), ('xxxhdpi', 432)]:
        # Full bleed dark background + centered emblem inside Android's 66dp safe area.
        icon = Image.new('RGB', (size, size), (1, 9, 27))
        art_size = round(size * 66 / 108)
        art = emblem.resize((art_size, art_size), Image.Resampling.LANCZOS)
        icon.paste(art, ((size - art_size) // 2, (size - art_size) // 2))
        icon.save(RES / f'mipmap-{density}/ic_launcher_foreground.png', optimize=True)


if __name__ == '__main__':
    main()
