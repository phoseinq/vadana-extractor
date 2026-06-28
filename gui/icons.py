"""Tiny self-contained line icons drawn with Pillow (no external assets / fonts).

Each icon is rendered at 4x and downscaled with LANCZOS, so the strokes come out
smooth and anti-aliased at small sizes. `icon(name, size, color)` returns a PIL
RGBA image; the GUI wraps it in a customtkinter CTkImage.
"""
from PIL import Image, ImageDraw

MUTED = (154, 164, 178, 255)
ACCENT = (45, 212, 191, 255)


def icon(name: str, size: int = 20, color=MUTED) -> Image.Image:
    s = size * 4
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    w = max(3, round(s * 0.075))
    m = s * 0.18

    if name == "doc":                                   # a page with text lines
        d.rounded_rectangle([m, m * 0.85, s - m, s - m * 0.85], radius=s * 0.07, outline=color, width=w)
        for i in range(3):
            y = s * 0.40 + i * s * 0.15
            d.line([m + s * 0.13, y, s - m - s * 0.13, y], fill=color, width=w)

    elif name == "board":                               # presentation board on a stand
        d.rounded_rectangle([m * 0.8, m, s - m * 0.8, s * 0.66], radius=s * 0.06, outline=color, width=w)
        d.line([s * 0.5, s * 0.66, s * 0.5, s * 0.80], fill=color, width=w)
        d.line([s * 0.34, s * 0.86, s * 0.66, s * 0.86], fill=color, width=w)

    elif name == "video":                               # play triangle in a rounded frame
        d.rounded_rectangle([m * 0.7, m, s - m * 0.7, s - m], radius=s * 0.12, outline=color, width=w)
        cx, cy, r = s * 0.5, s * 0.5, s * 0.14
        d.polygon([(cx - r * 0.8, cy - r), (cx - r * 0.8, cy + r), (cx + r, cy)], fill=color)

    elif name == "audio":                               # speaker + sound waves
        d.polygon([(m, s * 0.40), (s * 0.30, s * 0.40), (s * 0.48, s * 0.24),
                   (s * 0.48, s * 0.76), (s * 0.30, s * 0.60), (m, s * 0.60)], outline=color, width=w)
        d.arc([s * 0.42, s * 0.30, s * 0.74, s * 0.70], -55, 55, fill=color, width=w)
        d.arc([s * 0.50, s * 0.20, s * 0.92, s * 0.80], -55, 55, fill=color, width=w)

    elif name == "folder":                              # folder with a tab
        d.line([m, s * 0.34, s * 0.42, s * 0.34], fill=color, width=w)
        d.line([s * 0.42, s * 0.34, s * 0.50, s * 0.42], fill=color, width=w)
        d.rounded_rectangle([m, s * 0.40, s - m, s - m], radius=s * 0.07, outline=color, width=w)

    elif name == "search":                              # magnifier
        r = s * 0.30
        d.ellipse([m, m, m + 2 * r, m + 2 * r], outline=color, width=w)
        d.line([m + 2 * r * 0.86, m + 2 * r * 0.86, s - m * 0.7, s - m * 0.7], fill=color, width=w)

    elif name == "download":                            # arrow into a tray
        cx = s * 0.5
        d.line([cx, m, cx, s * 0.60], fill=color, width=w)
        d.line([cx - s * 0.13, s * 0.45, cx, s * 0.62], fill=color, width=w)
        d.line([cx + s * 0.13, s * 0.45, cx, s * 0.62], fill=color, width=w)
        d.line([m, s - m, s - m, s - m], fill=color, width=w)

    elif name == "info":                                # "i" in a circle
        d.ellipse([m, m, s - m, s - m], outline=color, width=w)
        cx = s * 0.5
        r = w * 0.7
        d.ellipse([cx - r, s * 0.32 - r, cx + r, s * 0.32 + r], fill=color)
        d.line([cx, s * 0.44, cx, s * 0.70], fill=color, width=w)

    return im.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":                              # render a preview sheet
    names = ["doc", "board", "video", "audio", "folder", "search", "download"]
    sheet = Image.new("RGBA", (len(names) * 64, 64), (18, 20, 26, 255))
    for i, n in enumerate(names):
        sheet.alpha_composite(icon(n, 40, ACCENT if i % 2 else MUTED), (i * 64 + 12, 12))
    sheet.convert("RGB").save("icons_preview.png")
    print("wrote icons_preview.png")
