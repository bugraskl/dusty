"""Draw the dusty icon (a box with dust sparkles) and save it as a multi-size .ico and .png.

Run once when the design changes: ``python packaging/make_icon.py``. Needs Pillow.
"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_ICO = os.path.join(HERE, "..", "dusty", "assets", "dusty.ico")
OUT_PNG = os.path.join(HERE, "..", "dusty", "assets", "dusty.png")

S = 1024  # draw large, downsample for crisp small sizes


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # rounded tile with a vertical gradient (warm amber → deep orange)
    tile = Image.new("RGBA", (S, S))
    td = ImageDraw.Draw(tile)
    top, bottom = (255, 190, 92), (226, 110, 40)
    for y in range(S):
        k = y / (S - 1)
        td.line([(0, y), (S, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * k) for i in range(3)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], radius=220, fill=255)
    img.paste(tile, (0, 0), mask)

    # cardboard box
    white = (255, 255, 255, 255)
    shade = (255, 236, 214, 255)
    bx0, by0, bx1, by1 = 250, 470, 774, 820
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=40, fill=white)
    d.polygon([(bx0 - 30, by0), (bx0 + 70, 380), (bx1 - 70, 380), (bx1 + 30, by0)], fill=shade)  # lid
    d.rounded_rectangle([430, 540, 594, 590], radius=25, fill=(226, 110, 40, 255))               # handle

    # dust sparkles
    def sparkle(cx, cy, r):
        w = r // 4
        d.polygon([(cx, cy - r), (cx + w, cy - w), (cx + r, cy), (cx + w, cy + w),
                   (cx, cy + r), (cx - w, cy + w), (cx - r, cy), (cx - w, cy - w)], fill=white)

    sparkle(330, 250, 90)
    sparkle(540, 190, 55)
    sparkle(720, 280, 70)
    return img


def main() -> None:
    os.makedirs(os.path.dirname(OUT_ICO), exist_ok=True)
    img = draw()
    img.resize((256, 256), Image.LANCZOS).save(OUT_PNG)
    img.save(OUT_ICO, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", os.path.normpath(OUT_ICO), "and", os.path.normpath(OUT_PNG))


if __name__ == "__main__":
    main()
