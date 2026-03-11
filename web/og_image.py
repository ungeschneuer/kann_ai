"""
Generiert Open-Graph-Preview-Bilder fuer Fragen.
Nutzt die lokal installierte DOS-Schrift und Pillow.
"""
import io
import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# Pfad zur DOS-Schrift (relativ zu diesem Modul)
FONT_DIR = Path(__file__).parent / "static" / "vendor" / "fonts"
FONT_DOS = str(FONT_DIR / "Perfect DOS VGA 437 Win.ttf")

# Bildgroesse (Standard OG-Format)
W, H = 1200, 630

# TUI-Farben
COLOR_BG      = (0,   0,   0)    # schwarz
COLOR_BLUE    = (0,   0, 168)    # #0000a8
COLOR_WHITE   = (168, 168, 168)  # #a8a8a8
COLOR_BRIGHT  = (255, 255, 255)  # weiss
COLOR_CYAN    = (0,  168, 168)   # #00a8a8
COLOR_GRAY    = (80,  80,  80)

# Rahmen-Abstände
PAD   = 60   # Außenabstand
INNER = 80   # Innenabstand


def _font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_DOS, size)
    except Exception:
        return ImageFont.load_default()


def _draw_tui_border(draw: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int,
                     color=COLOR_WHITE, double: bool = True):
    """Zeichnet einen einfachen oder doppelten TUI-Rahmen."""
    # Horizontale Linien – als Rechteck einfacher
    draw.rectangle([x0, y0, x1, y0 + 2], fill=color)
    draw.rectangle([x0, y1 - 2, x1, y1], fill=color)
    draw.rectangle([x0, y0, x0 + 2, y1], fill=color)
    draw.rectangle([x1 - 2, y0, x1, y1], fill=color)
    if double:
        draw.rectangle([x0 + 4, y0 + 4, x1 - 4, y0 + 6], fill=color)
        draw.rectangle([x0 + 4, y1 - 6, x1 - 4, y1 - 4], fill=color)
        draw.rectangle([x0 + 4, y0 + 4, x0 + 6, y1 - 4], fill=color)
        draw.rectangle([x1 - 6, y0 + 4, x1 - 4, y1 - 4], fill=color)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Bricht Text auf eine maximale Pixelbreite um."""
    words = text.split()
    lines: list[str] = []
    current = ""
    dummy_img = Image.new("RGB", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)

    for word in words:
        candidate = (current + " " + word).strip()
        bbox = dummy_draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] > max_width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def generate_og_image(question: str, site_name: str = "Kann KI?",
                      vote_counts: dict | None = None,
                      site_url: str = "") -> bytes:
    """
    Erzeugt ein 1200x630 OG-Preview-Bild als PNG-Bytes.
    """
    img = Image.new("RGB", (W, H), COLOR_BG)
    draw = ImageDraw.Draw(img)

    # Hintergrund: subtiles Rastermuster (simuliert tui-bg-cyan-black)
    dot_color = (0, 30, 30)
    for x in range(0, W, 4):
        for y in range(0, H, 4):
            draw.point((x, y), fill=dot_color)

    # Blaues Fenster
    win_x0, win_y0 = PAD, PAD
    win_x1, win_y1 = W - PAD, H - PAD
    draw.rectangle([win_x0, win_y0, win_x1, win_y1], fill=COLOR_BLUE)

    # Doppelter Rahmen
    _draw_tui_border(draw, win_x0, win_y0, win_x1, win_y1, COLOR_WHITE)

    # Titelleiste
    title_h = 50
    draw.rectangle([win_x0 + 8, win_y0 + 8, win_x1 - 8, win_y0 + 8 + title_h], fill=COLOR_WHITE)

    font_title  = _font(28)
    font_site   = _font(22)
    font_small  = _font(18)

    # Site-Name in Titelleiste
    draw.text((win_x0 + 24, win_y0 + 18), f" {site_name} ", font=font_site, fill=COLOR_BLUE)
    # Schließen-Symbol rechts
    draw.text((win_x1 - 50, win_y0 + 18), "■", font=font_site, fill=COLOR_BLUE)

    # Trennlinie nach Titelleiste
    ty = win_y0 + 8 + title_h + 4
    draw.rectangle([win_x0 + 8, ty, win_x1 - 8, ty + 2], fill=COLOR_WHITE)

    # Frage-Text: Schriftgröße automatisch anpassen damit Text ins Fenster passt
    win_w      = win_x1 - win_x0
    max_text_w = win_w - INNER * 2          # verfuegbare Breite
    url_reserved = 50                        # Platz fuer URL-Zeile unten
    content_area_top    = ty + 10
    content_area_bottom = win_y1 - url_reserved
    content_area_h      = content_area_bottom - content_area_top

    # Starte mit 25% groesserem Basiswert (32 * 1.25 = 40), verkleinere bis alles passt
    for font_size in range(64, 18, -1):
        font_q = _font(font_size)
        line_h = int(font_size * 1.45)
        lines  = _wrap_text(question, font_q, max_text_w)
        if len(lines) * line_h <= content_area_h:
            break

    # If text still exceeds 4 lines at minimum font size, truncate with ellipsis
    max_lines = content_area_h // line_h
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        if lines:
            lines[-1] = lines[-1].rstrip() + "\u2026"

    text_block_h = len(lines) * line_h

    # Vertikal zentrieren
    content_y = content_area_top + (content_area_h - text_block_h) // 2

    # Jede Zeile horizontal zentrieren
    center_x = win_x0 + win_w // 2
    for i, line in enumerate(lines):
        bbox   = draw.textbbox((0, 0), line, font=font_q)
        line_w = bbox[2] - bbox[0]
        x      = center_x - line_w // 2
        draw.text((x, content_y + i * line_h), line, font=font_q, fill=COLOR_BRIGHT)

    # URL unten rechts (rechtsbündig)
    if not site_url:
        site_url = os.getenv("WEBSITE_URL", "")
    if site_url:
        url_bbox = draw.textbbox((0, 0), site_url, font=font_small)
        url_w = url_bbox[2] - url_bbox[0]
        url_x = win_x1 - INNER // 2 - url_w
        url_y = win_y1 - 38
        draw.text((url_x, url_y), site_url, font=font_small, fill=COLOR_CYAN)

    # Als Bytes ausgeben
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
