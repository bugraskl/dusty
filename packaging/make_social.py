"""Render docs/social-preview.png (1280×640) for the GitHub social preview. Needs Pillow."""
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
W, H = 1280, 640


def font(names, size):
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> None:
    img = Image.new("RGB", (W, H), (250, 246, 240))
    d = ImageDraw.Draw(img)
    for y in range(H):                      # soft warm gradient
        k = y / H
        d.line([(0, y), (W, y)], fill=(int(255 - 10 * k), int(248 - 18 * k), int(238 - 30 * k)))

    icon = Image.open(os.path.join(ROOT, "dusty", "assets", "dusty.png")).convert("RGBA").resize((150, 150))
    img.paste(icon, (80, 90), icon)
    bold = font(["segoeuib.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"], 96)
    reg = font(["segoeui.ttf", "DejaVuSans.ttf", "Arial.ttf"], 36)
    small = font(["segoeui.ttf", "DejaVuSans.ttf", "Arial.ttf"], 28)
    d.text((260, 100), "dusty", font=bold, fill=(40, 30, 25))
    d.text((266, 232), "Free up disk space without losing anything", font=reg, fill=(90, 70, 60))
    lines = ["Finds what you haven't touched in a year",
             "Backs it up to Google Drive / OneDrive / any folder",
             "Verifies the copy, then deletes the original",
             "Portable Windows exe  ·  open source  ·  MIT"]
    for i, ln in enumerate(lines):
        y = 330 + i * 52
        d.ellipse([86, y + 12, 100, y + 26], fill=(226, 110, 40))
        d.text((118, y), ln, font=small, fill=(60, 50, 45))

    shot = Image.open(os.path.join(ROOT, "docs", "screenshot.png")).convert("RGB")
    shot = shot.crop((0, 0, 900, 420)).resize((390, 182), Image.LANCZOS)
    frame = Image.new("RGBA", (shot.width + 12, shot.height + 12), (226, 110, 40, 255))
    frame.paste(shot, (6, 6))
    frame = frame.rotate(-4, expand=True, resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0))
    img.paste(frame, (W - frame.width - 36, H - frame.height - 60), frame)
    out = os.path.join(ROOT, "docs", "social-preview.png")
    img.save(out, optimize=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
