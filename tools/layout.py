#!/usr/bin/env python3
"""
layout.py — Sistema de layout por ZONAS para Shorts 1080x1920 (corrección 2026-10-20).

Causa raíz del defecto original: la portada (con el título completo) se usaba
como fondo del video y el filtro subtitles de ffmpeg dibujaba los subtítulos
en la MISMA zona central → texto superpuesto, ilegible y cortado por el borde.

Regla nueva — tres zonas que NUNCA se tocan (en píxeles, alto 1920):
  - SUPERIOR   y 0..345     (0-18%) : SOLO franja de marca/kicker corto
                                      (máx 5 palabras, ej. «DINERO EN USA · IRS»).
                                      El título completo NUNCA se quema en el video:
                                      vive solo en los metadatos de YouTube.
  - CENTRAL    y 345..1382  (18-72%): el visual protagonista.
        · Estándar: UN dato grande tipográfico por escena + 1 línea de apoyo.
        · Animado:  escena iconográfica flat geométrica (iconos en este módulo)
                    + dato + apoyo. Nada de personajes dibujados con primitivas.
  - INFERIOR   y 1382..1766 (72-92%): SOLO subtítulos, máx 2 líneas, envueltos
                                      a <=88% del ancho, con márgenes reales,
                                      dentro de pastilla semitransparente.
  - y 1766..1920 (92-100%): respiro vacío. Ningún texto entra jamás aquí.

Todo texto se MIDE con PIL (textbbox/textlength) antes de dibujar: si no cabe,
se reduce la fuente o se envuelve; si ni así cabe, se lanza LayoutError.
Prohibido dibujar fuera de márgenes.
"""
import textwrap
from pathlib import Path

W, H = 1080, 1920
MARGIN_X = 65                      # margen lateral real (texto máx 950 px = 88%)
TEXT_MAX_W = W - 2 * MARGIN_X      # 950
ZONE_TOP = (0, 345)                # 0-18%
ZONE_MID = (345, 1382)             # 18-72%
ZONE_SUB = (1382, 1766)            # 72-92%
FOOT_PAD = 30

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
BG = "#0A1F14"; BG_DEEP = "#07130C"; PANEL = "#11382A"; PANEL_SOFT = "#0E2A1C"
ACCENT = "#1DB954"; GOLD = "#F2C14E"; WHITE = "#FFFFFF"; SOFT = "#CFE3D6"
INK = "#0A1F14"; PAPER = "#EAF4EC"; LINE = "#9DB8A8"

class LayoutError(Exception):
    pass

# ---------------------------------------------------------------- fuentes/medición
_cache = {}
def font(size: int):
    from PIL import ImageFont
    if size not in _cache:
        _cache[size] = ImageFont.truetype(FONT_PATH, size)
    return _cache[size]

def text_w(draw, text: str, size: int) -> float:
    return draw.textlength(text, font=font(size))

def fit_font_size(draw, text: str, max_w: int, start: int, minimum: int) -> int:
    """Mayor tamaño <= start con el que `text` cabe en max_w; LayoutError si ni al mínimo."""
    size = start
    while size > minimum and text_w(draw, text, size) > max_w:
        size -= 4
    if text_w(draw, text, size) > max_w:
        raise LayoutError(f"texto no cabe ni a {minimum}px en {max_w}px: {text!r}")
    return size

def wrap_measured(draw, text: str, size: int, max_w: int) -> list[str]:
    """Envuelve por palabras midiendo con PIL (no por conteo de caracteres)."""
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        trial = f"{cur} {w_}".strip()
        if text_w(draw, trial, size) <= max_w:
            cur = trial
        else:
            if cur: lines.append(cur)
            if text_w(draw, w_, size) > max_w:
                raise LayoutError(f"palabra más ancha que la zona a {size}px: {w_!r}")
            cur = w_
    if cur: lines.append(cur)
    return lines

# ---------------------------------------------------------------- escenas del guión
ICONS = ("edificio", "calendario", "tarjeta", "grafica", "moneda", "documento", "telefono")

def effective_scenes(script: dict) -> list[dict]:
    """Escenas visuales efectivas: las del guión (scenes_visual) o derivadas de
    on_screen_text. Cada escena: {big, support, icon} alineada a las secciones
    (gancho + bloques + cierre)."""
    sections = script.get("sections", {}) or {}
    n = 1 + len(sections.get("desarrollo") or []) + (1 if sections.get("cierre_cta") else 0)
    given = script.get("scenes_visual") or []
    if len(given) >= n:
        return [dict(s) for s in given[:n]]
    on = script.get("on_screen_text") or []
    scenes = []
    for i in range(n):
        src = on[min(i, len(on) - 1)] if on else (script.get("topic", "")[:40])
        scenes.append({"big": src[:24].upper(), "support": "", "icon": "grafica"})
    return scenes

def section_texts(script: dict) -> list[str]:
    s = script.get("sections", {}) or {}
    out = [s.get("hook_0_3s", "")]
    out += list(s.get("desarrollo") or [])
    if s.get("cierre_cta"): out.append(s["cierre_cta"])
    return [t for t in out if t.strip()] or [script.get("full_text", "")]

def caption_chunks(script: dict, size: int = 60, max_lines: int = 2) -> list[dict]:
    """Trocea el texto narrado en subtítulos que CABEN: cada trozo envuelve a
    <=max_lines líneas a `size` px dentro de TEXT_MAX_W. Devuelve
    [{text, words, scene}] con la escena (por conteo acumulado de palabras)."""
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (W, H)))
    sections = section_texts(script)
    bounds, acc = [], 0
    for t in sections:
        acc += len(t.split()); bounds.append(acc)
    def scene_of(word_idx):
        for i, b in enumerate(bounds):
            if word_idx < b: return i
        return len(bounds) - 1
    words = script.get("full_text", "").split()
    chunks, cur, start = [], [], 0
    for i, w_ in enumerate(words):
        trial = cur + [w_]
        if len(wrap_measured(d, " ".join(trial), size, TEXT_MAX_W)) <= max_lines and len(trial) <= 9:
            cur = trial
        else:
            if cur: chunks.append({"text": " ".join(cur), "words": len(cur), "scene": scene_of(start)})
            cur, start = [w_], i
            if len(wrap_measured(d, w_, size, TEXT_MAX_W)) > max_lines:
                raise LayoutError(f"palabra imposible de subtitular: {w_!r}")
    if cur: chunks.append({"text": " ".join(cur), "words": len(cur), "scene": scene_of(start)})
    return chunks

def validate_layout(script: dict) -> list[str]:
    """Asserts de layout (los usa automation/qc.py): devuelve lista de fallos."""
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (W, H)))
    fails = []
    kicker = (script.get("kicker") or "").strip()
    kwords = [w for w in kicker.replace("·", " ").split() if w]  # «·» es separador, no palabra
    if not kicker:
        fails.append("sin kicker de zona superior")
    elif len(kwords) > 5:
        fails.append(f"kicker de {len(kwords)} palabras (>5): {kicker!r}")
    else:
        try: fit_font_size(d, kicker.upper(), TEXT_MAX_W - 120, 44, 30)
        except LayoutError as e: fails.append(f"kicker: {e}")
    for i, sc in enumerate(effective_scenes(script)):
        big = (sc.get("big") or "").strip()
        if not big:
            fails.append(f"escena {i + 1}: sin dato grande"); continue
        try: fit_font_size(d, big, TEXT_MAX_W, 300, 56)
        except LayoutError as e: fails.append(f"escena {i + 1} big: {e}")
        sup = (sc.get("support") or "").strip()
        if sup:
            try:
                lines = wrap_measured(d, sup, 54, TEXT_MAX_W)
                if len(lines) > 2: fails.append(f"escena {i + 1}: apoyo de {len(lines)} líneas (>2)")
            except LayoutError as e: fails.append(f"escena {i + 1} apoyo: {e}")
    try:
        ch = caption_chunks(script)
        if not ch: fails.append("sin subtítulos generables")
    except LayoutError as e:
        fails.append(f"subtítulos: {e}")
    return fails

# ---------------------------------------------------------------- iconografía flat
def draw_icon(d, name: str, cx: int, cy: int, size: int):
    """Iconografía flat geométrica y limpia. `size` = ancho aprox. del icono.
    Sin personajes: solo formas simples, paleta del canal, mucho aire."""
    s = size / 440.0  # los iconos se diseñan sobre una caja de 440
    def R(x0, y0, x1, y1): return [cx + (x0 - 220) * s, cy + (y0 - 220) * s, cx + (x1 - 220) * s, cy + (y1 - 220) * s]
    def P(x, y): return (cx + (x - 220) * s, cy + (y - 220) * s)
    if name == "edificio":  # banco / institución: frontón, columnas, base
        d.polygon([P(30, 150), P(410, 150), P(220, 34)], fill=GOLD)
        d.ellipse(R(190, 78, 250, 138), fill=BG)
        d.rectangle(R(52, 162, 388, 186), fill=PAPER)
        for i in range(4):
            x = 82 + i * 82
            d.rectangle(R(x, 206, x + 38, 356), fill=PAPER)
        d.rectangle(R(52, 372, 388, 396), fill=PAPER)
        d.rectangle(R(30, 408, 410, 428), fill=PAPER)
    elif name == "calendario":
        d.rounded_rectangle(R(60, 70, 380, 400), radius=int(28 * s), fill=PAPER)
        d.rectangle(R(60, 70, 380, 160), fill=ACCENT)
        for x in (130, 292):
            d.rounded_rectangle(R(x, 40, x + 18, 105), radius=int(9 * s), fill=GOLD)
        for r in range(3):
            for c in range(3):
                d.ellipse(R(105 + c * 82, 205 + r * 58, 135 + c * 82, 235 + r * 58), fill=LINE)
    elif name == "tarjeta":
        d.rounded_rectangle(R(20, 110, 420, 350), radius=int(30 * s), fill=PAPER)
        d.rectangle(R(20, 160, 420, 205), fill=INK)
        d.rounded_rectangle(R(52, 245, 118, 292), radius=int(8 * s), fill=GOLD)
        d.rectangle(R(52, 316, 190, 332), fill=LINE)
        d.rectangle(R(300, 316, 388, 332), fill=LINE)
    elif name == "grafica":
        d.line(R(60, 60, 60, 380), fill=SOFT, width=max(4, int(10 * s)))
        d.line(R(60, 380, 400, 380), fill=SOFT, width=max(4, int(10 * s)))
        bars = [(95, 300), (165, 250), (235, 275), (305, 170)]
        for i, (x, top) in enumerate(bars):
            d.rectangle(R(x, top, x + 48, 380), fill=GOLD if i == len(bars) - 1 else ACCENT)
        pts = [(119, 275), (189, 225), (259, 250), (340, 130)]
        pts = [(cx + (x - 220) * s, cy + (y - 220) * s) for x, y in pts]
        d.line(pts, fill=WHITE, width=max(4, int(12 * s)))
        d.polygon([pts[-1], (pts[-1][0] - 34 * s, pts[-1][1] + 2), (pts[-1][0] - 6 * s, pts[-1][1] + 32 * s)], fill=WHITE)
    elif name == "moneda":
        d.ellipse(R(70, 70, 370, 370), fill=GOLD)
        d.ellipse(R(105, 105, 335, 335), outline="#C9971F", width=max(3, int(8 * s)))
        f = font(int(190 * s))
        t = "$"
        tw = d.textlength(t, font=f)
        bbox = d.textbbox((0, 0), t, font=f)
        d.text((cx - tw / 2, cy - (bbox[3] - bbox[1]) / 2 - bbox[1]), t, font=f, fill=INK)
    elif name == "documento":
        d.rounded_rectangle(R(110, 40, 330, 410), radius=int(16 * s), fill=PAPER)
        d.polygon([P(266, 42), P(328, 104), P(266, 104)], fill=LINE)
        for i in range(4):
            d.rectangle(R(150, 140 + i * 52, 292, 158 + i * 52), fill=LINE)
        d.ellipse(R(238, 292, 338, 392), fill=ACCENT)
        d.line([P(263, 342), P(283, 362), P(315, 320)], fill=WHITE, width=max(3, int(11 * s)))
    elif name == "telefono":
        d.rounded_rectangle(R(130, 30, 310, 410), radius=int(34 * s), outline=PAPER, width=max(3, int(10 * s)))
        d.rectangle(R(130, 92, 310, 96), fill=PAPER)
        d.rounded_rectangle(R(152, 128, 262, 190), radius=int(26 * s), fill=ACCENT)
        d.rounded_rectangle(R(178, 212, 288, 274), radius=int(26 * s), fill=PANEL)
        d.rectangle(R(196, 368, 244, 380), fill=PAPER)
    else:  # fallback limpio: círculo de acento con punto
        d.ellipse(R(120, 120, 320, 320), fill=ACCENT)
        d.ellipse(R(185, 185, 255, 255), fill=BG)

# ---------------------------------------------------------------- composición de escenas
def _draw_kicker(d, kicker: str):
    """Pastilla de kicker centrada en la zona superior, medida antes de dibujar.
    Sirve igual sobre fondo plano (formatos estándar/icono) que sobre foto
    (formato foto_real): la pastilla trae su propio fondo."""
    k = (kicker or "DINERO EN USA").upper()
    size = fit_font_size(d, k, TEXT_MAX_W - 160, 44, 30)
    tw = text_w(d, k, size)
    pw, ph = tw + 72, 92
    x0, y0 = (W - pw) / 2, 120
    d.rounded_rectangle([x0, y0, x0 + pw, y0 + ph], radius=46, fill=PANEL)
    d.ellipse([x0 + 28, y0 + ph / 2 - 9, x0 + 46, y0 + ph / 2 + 9], fill=ACCENT)
    bbox = d.textbbox((0, 0), k, font=font(size))
    d.text((x0 + 62, y0 + ph / 2 - (bbox[3] - bbox[1]) / 2 - bbox[1]), k, font=font(size), fill=WHITE)

def _base(kicker: str):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, ZONE_MID[1], W, H], fill=BG_DEEP)          # zona inferior reservada
    d.rectangle([0, ZONE_TOP[1] - 3, W, ZONE_TOP[1]], fill=PANEL_SOFT)
    _draw_kicker(d, kicker)
    return img, d

def _support(d, text: str, y_center: int):
    if not text: return
    lines = wrap_measured(d, text, 54, TEXT_MAX_W)
    if len(lines) > 2: raise LayoutError(f"apoyo de {len(lines)} líneas: {text!r}")
    f = font(54); lh = 70
    y = y_center - (len(lines) * lh) / 2
    for ln in lines:
        tw = text_w(d, ln, 54)
        d.text(((W - tw) / 2, y), ln, font=f, fill=SOFT)
        y += lh

def _big(d, text: str, y_center: int, color=WHITE, start=300):
    size = fit_font_size(d, text, TEXT_MAX_W, start, 56)
    f = font(size)
    tw = text_w(d, text, size)
    bbox = d.textbbox((0, 0), text, font=f)
    d.text(((W - tw) / 2, y_center - (bbox[3] - bbox[1]) / 2 - bbox[1]), text, font=f, fill=color)
    return size

def make_scene_standard(scene: dict, kicker: str):
    """Estándar: protagonismo tipográfico — UN dato grande + línea de apoyo."""
    img, d = _base(kicker)
    big = (scene.get("big") or "").strip()
    color = GOLD if any(c.isdigit() for c in big) else WHITE
    size = _big(d, big, 800, color=color)
    d.rectangle([(W - 120) / 2, 800 + size * 0.72, (W + 120) / 2, 800 + size * 0.72 + 10], fill=ACCENT)
    _support(d, scene.get("support", ""), 1130)
    return img

def make_scene_animated(scene: dict, kicker: str):
    """Animado: icono flat protagonista + dato + apoyo, con mucho aire."""
    from PIL import Image, ImageDraw
    img, d = _base(kicker)
    icon = scene.get("icon", "grafica")
    if icon not in ICONS: icon = "grafica"
    d.ellipse([(W - 560) / 2, 430, (W + 560) / 2, 990], fill=PANEL_SOFT)
    draw_icon(d, icon, W // 2, 710, 400)
    _big(d, (scene.get("big") or "").strip(), 1120, color=WHITE, start=170)
    _support(d, scene.get("support", ""), 1300)
    return img

def caption_overlay(base_img, text: str):
    """Dibuja el subtítulo en su pastilla, SOLO dentro de la zona inferior."""
    from PIL import Image, ImageDraw
    img = base_img.copy()
    d = ImageDraw.Draw(img, "RGBA")
    size = 60
    lines = wrap_measured(d, text, size, TEXT_MAX_W)
    if len(lines) > 2: raise LayoutError(f"subtítulo de {len(lines)} líneas: {text!r}")
    lh = 76
    tw = max(text_w(d, ln, size) for ln in lines)
    pw, ph = tw + 64, len(lines) * lh + 44
    zone_h = ZONE_SUB[1] - ZONE_SUB[0]
    if ph > zone_h: raise LayoutError("pastilla de subtítulo más alta que su zona")
    x0 = (W - pw) / 2; y0 = ZONE_SUB[0] + (zone_h - ph) / 2
    d.rounded_rectangle([x0, y0, x0 + pw, y0 + ph], radius=28, fill=(0, 0, 0, 178))
    y = y0 + 22
    for ln in lines:
        lw = text_w(d, ln, size)
        bbox = d.textbbox((0, 0), ln, font=font(size))
        d.text(((W - lw) / 2, y - bbox[1]), ln, font=font(size), fill=WHITE)
        y += lh
    return img

def scene_durations(script: dict, total_sec: float) -> list[float]:
    secs = section_texts(script)
    words = [max(1, len(t.split())) for t in secs]
    tot = sum(words)
    return [total_sec * w / tot for w in words]

# ---------------------------------------------------------------- formato «foto real»
# Orden del dueño (2026-10-20, SUPERSEDE a la de imagen generada): «Quita esa
# imagen de fondo; poner una imagen realista del tema en alta calidad». El
# formato con imagen usa FOTOGRAFÍA REAL del tema en alta resolución, de
# fuentes con licencia libre o dominio público (Wikimedia Commons, Pexels,
# Unsplash), con procedencia y licencia registradas en el manifiesto.
# PROHIBIDO en este formato: imágenes generadas por IA, iconos y personajes
# PIL. Las fotos viven en assets/real/<tema>/ con manifest.json. SIN
# manifiesto de fotos reales, sin procedencia/licencia o sin foto para una
# escena, el render FALLA con mensaje claro: jamás se cae a generadas ni a
# iconos en silencio.
ZONE_DATA = (1114, 1382)           # franja del dato grande: 58-72%
ROOT_DIR = Path(__file__).resolve().parent.parent
REAL_ROOT = ROOT_DIR / "assets" / "real"
GENERATED_ROOT = REAL_ROOT         # compat: nombre histórico; hoy apunta a fotos reales
# Afinidad icono del guión -> rol de foto cuando la escena no declara image_role.
ROLE_AFFINITY = {"edificio": "banco", "grafica": "banco", "tarjeta": "tarjeta",
                 "moneda": "calendario", "calendario": "calendario",
                 "documento": "calendario", "telefono": "tarjeta"}

def _entry_get(entry: dict, *keys):
    for k in keys:
        v = entry.get(k)
        if v not in (None, ""):
            return v
    return ""

def real_theme(script: dict):
    r = script.get("real") or {}
    if r.get("theme"):
        return r["theme"]
    g = script.get("generated") or {}   # compat: guiones viejos traen el tema aquí
    return g.get("theme") or script.get("real_theme") or script.get("generated_theme")

def real_dir(script: dict) -> Path:
    r = script.get("real") or {}
    if r.get("dir"):
        p = Path(r["dir"])
        return p if p.is_absolute() else ROOT_DIR / p
    return REAL_ROOT / (real_theme(script) or "")

def load_real_manifest(script: dict):
    """Devuelve (directorio, datos) o (directorio, None) si no hay manifiesto."""
    import json
    d = real_dir(script)
    r = script.get("real") or {}
    if r.get("manifest"):
        p = Path(r["manifest"])
        mf = p if p.is_absolute() else ROOT_DIR / p
        d = mf.parent
    else:
        mf = d / "manifest.json"
    if not mf.exists():
        return d, None
    try:
        return d, json.loads(mf.read_text(encoding="utf-8"))
    except Exception:
        return d, None

def assign_real_images(script: dict):
    """Resuelve la FOTO REAL de CADA escena. Devuelve (asignaciones, fallos):
    asignaciones[i] = {path, file, role, source, source_url, license, author,
    crop_centering, manifest_dimensions} o None si no se pudo.
    Reglas: image_role de la escena > afinidad por icono > orden del manifiesto."""
    scenes = effective_scenes(script)
    d, data = load_real_manifest(script)
    if data is None:
        return [None] * len(scenes), [f"sin manifiesto de fotos reales en {d} "
                                      "(assets/real/<tema>/manifest.json con procedencia y licencia es obligatorio)"]
    entries = data.get("scenes") or []
    by_role = {e.get("role"): e for e in entries if e.get("role")}
    fails, out = [], []
    for i, sc in enumerate(scenes):
        role = sc.get("image_role") or ROLE_AFFINITY.get(sc.get("icon", ""))
        entry = by_role.get(role) if role else None
        if entry is None and i < len(entries):
            entry = entries[i]
        if entry is None:
            fails.append(f"escena {i + 1}: sin foto real asignable (rol {role!r})")
            out.append(None); continue
        f = _entry_get(entry, "file", "archivo")
        path = Path(f) if Path(f).is_absolute() else d / f
        out.append({"path": path, "file": f, "role": entry.get("role", role),
                    "source": _entry_get(entry, "source", "fuente"),
                    "source_url": _entry_get(entry, "source_url", "url_origen"),
                    "license": _entry_get(entry, "license", "licencia"),
                    "author": _entry_get(entry, "author", "autor"),
                    "crop_centering": entry.get("crop_centering"),
                    "manifest_dimensions": entry.get("dimensions") or entry.get("dimensiones")})
    return out, fails

def validate_real_images(script: dict) -> list[str]:
    """Puertas del formato foto_real (las usa automation/qc.py): manifiesto de
    fotos reales con procedencia (fuente + URL de origen) y licencia por foto,
    una foto por escena, archivos existentes y resolución suficiente para el
    crop vertical 1080x1920 (lado útil del crop >= 1000 px). Un manifiesto de
    imágenes generadas (con prompts, sin procedencia) se RECHAZA."""
    from PIL import Image
    d, data = load_real_manifest(script)
    fails = []
    if data is not None:
        fmt = str(data.get("format") or data.get("formato") or "foto_real")
        if fmt != "foto_real":
            fails.append(f"el manifiesto de {d} declara format={fmt!r}, no 'foto_real' "
                         "(las imágenes generadas por IA están prohibidas en este formato)")
    assigns, afails = assign_real_images(script)
    fails += list(afails)
    for i, a in enumerate(assigns):
        if a is None: continue
        if not str(a["source"]).strip():
            fails.append(f"escena {i + 1}: la foto {a['file']!r} no registra fuente en el manifiesto")
        if not str(a["source_url"]).startswith("http"):
            fails.append(f"escena {i + 1}: la foto {a['file']!r} no registra URL de origen válida")
        if not str(a["license"]).strip():
            fails.append(f"escena {i + 1}: la foto {a['file']!r} no registra licencia en el manifiesto")
        cc = a.get("crop_centering")
        if cc is not None and not (isinstance(cc, (list, tuple)) and len(cc) == 2
                                   and all(isinstance(v, (int, float)) and 0.0 <= v <= 1.0 for v in cc)):
            fails.append(f"escena {i + 1}: crop_centering inválido en el manifiesto: {cc!r}")
        p = a["path"]
        if not p.exists():
            fails.append(f"escena {i + 1}: no existe la foto real {p}")
            continue
        try:
            with Image.open(p) as im:
                w, h = im.size
            if w < 1200 or h < 1200:
                fails.append(f"escena {i + 1}: foto {a['file']!r} de baja resolución ({w}x{h}; mínimo 1200x1200)")
            crop_w = (h * 9 / 16) if w > h else w   # lado útil del crop vertical 9:16
            if crop_w < 1000:
                fails.append(f"escena {i + 1}: el crop vertical de {a['file']!r} quedaría a {int(crop_w)} px (<1000): buscar otra foto")
            md = a.get("manifest_dimensions")
            if md:
                if isinstance(md, dict):
                    mw, mh = md.get("width"), md.get("height")
                else:
                    parts = str(md).lower().split("x")
                    mw, mh = (int(parts[0]), int(parts[1])) if len(parts) == 2 else (None, None)
                if (mw, mh) != (w, h):
                    fails.append(f"escena {i + 1}: dimensiones del manifiesto ({mw}x{mh}) no coinciden con el archivo ({w}x{h})")
        except Exception as e:
            fails.append(f"escena {i + 1}: foto ilegible {a['file']!r}: {e}")
    return fails

def _gradient_overlay(img, top_alpha=165, bottom_start=980, bottom_alpha=238):
    """Degradado oscuro del canal: arriba para que la pastilla del kicker respire
    y abajo (fuerte desde el ~51%) para que dato y subtítulos lean sobre la foto."""
    from PIL import Image
    ov = Image.new("L", (1, H))
    px = []
    for y in range(H):
        if y < ZONE_TOP[1]:
            a = int(top_alpha * (1 - y / ZONE_TOP[1]))
        elif y < bottom_start:
            a = 0
        else:
            a = int(bottom_alpha * (y - bottom_start) / (H - bottom_start))
        px.append(a)
    ov.putdata(px)
    ov = ov.resize((W, H))
    dark = Image.new("RGB", (W, H), BG_DEEP)
    return Image.composite(dark, img, ov)

def make_scene_real(scene: dict, kicker: str, image_path, flip: bool = False, crop_centering=(0.5, 0.5)):
    """Escena del formato foto real: FOTOGRAFÍA REAL a PANTALLA COMPLETA
    (cover-crop 9:16 con foco opcional `crop_centering` del manifiesto) +
    degradado + kicker arriba + dato grande con apoyo en la franja 58-72%
    (ZONE_DATA) sobre pastilla semitransparente. Todo texto medido con PIL.
    Los subtítulos NO van aquí: los compone caption_overlay en su zona."""
    from PIL import Image, ImageDraw, ImageOps
    try:
        centering = (float(crop_centering[0]), float(crop_centering[1]))
        if not (0.0 <= centering[0] <= 1.0 and 0.0 <= centering[1] <= 1.0):
            centering = (0.5, 0.5)
    except Exception:
        centering = (0.5, 0.5)
    src = Image.open(image_path).convert("RGB")
    img = ImageOps.fit(src, (W, H), centering=centering)   # cover-crop a 1080x1920
    if flip: img = ImageOps.mirror(img)        # reuso sin repetir idéntico
    img = _gradient_overlay(img)
    d = ImageDraw.Draw(img, "RGBA")
    _draw_kicker(d, kicker)
    # Dato grande + apoyo dentro de ZONE_DATA, sobre pastilla semitransparente.
    big = (scene.get("big") or "").strip()
    sup = (scene.get("support") or "").strip()
    band_h = ZONE_DATA[1] - ZONE_DATA[0]
    sup_size, sup_lh = 50, 64
    sup_lines = wrap_measured(d, sup, sup_size, TEXT_MAX_W) if sup else []
    if len(sup_lines) > 2:
        raise LayoutError(f"apoyo de {len(sup_lines)} líneas en escena de foto real: {sup!r}")
    size = fit_font_size(d, big, TEXT_MAX_W, 190, 56)
    while size > 56:
        bb = d.textbbox((0, 0), big, font=font(size))
        need = (bb[3] - bb[1]) + (10 if sup_lines else 0) + len(sup_lines) * sup_lh + 44
        if need <= band_h: break
        size -= 6
    bb = d.textbbox((0, 0), big, font=font(size))
    big_h = bb[3] - bb[1]
    content_h = big_h + (10 if sup_lines else 0) + len(sup_lines) * sup_lh
    if content_h + 28 > band_h:
        raise LayoutError(f"dato+apoyo no caben en la franja 58-72%: {big!r} / {sup!r}")
    pad = 26
    py0 = ZONE_DATA[0] + (band_h - (content_h + 2 * pad)) / 2
    d.rounded_rectangle([36, py0, W - 36, py0 + content_h + 2 * pad], radius=30,
                        fill=(5, 15, 9, 205))
    color = GOLD if any(c.isdigit() for c in big) else WHITE
    tw = text_w(d, big, size)
    d.text(((W - tw) / 2, py0 + pad - bb[1]), big, font=font(size), fill=color)
    y = py0 + pad + big_h + 10
    for ln in sup_lines:
        lw = text_w(d, ln, sup_size)
        lb = d.textbbox((0, 0), ln, font=font(sup_size))
        d.text(((W - lw) / 2, y - lb[1]), ln, font=font(sup_size), fill=SOFT)
        y += sup_lh
    return img

# ------------------------------------------------- compatibilidad (nombres viejos)
# El formato se llamaba «imagen_generada» hasta la orden de foto real del
# dueño (2026-10-20). Estos alias mantienen importable el código anterior,
# pero TODOS resuelven al sistema de fotos reales: un guión viejo sin bloque
# «real» busca su tema en assets/real/<tema>/ y falla si no hay fotos reales.
generated_theme = real_theme
generated_dir = real_dir
load_generated_manifest = load_real_manifest
assign_generated_images = assign_real_images
validate_generated_images = validate_real_images
make_scene_generated = make_scene_real

# ------------------------------------------------- formato «metraje real»
# ESTÁNDAR VIGENTE del canal (orden del dueño 2026-10-20, MANDATO §3d;
# SUPERSEDE a foto_real §3c): METRAJE REAL de personas reales en VIDEO
# (b-roll de oficina / actividad real del tema — no foto fija, no zoom sobre
# fotos como recurso principal) + voz en off en español a ritmo 1.20× +
# sobre el video SOLO los titulares cortos del guión (máx ~5 palabras por
# escena) + subtítulos completos en su zona inferior + TARJETA DE CIERRE
# con el emblema del canal. NADA animado, NADA de diapositivas de texto.
# Listón de acabado (orden 2026-10-20, CORREGIDO el mismo día por el
# dueño: lo rápido se sentía agitado, no fluido): cortes cada 4-6 s —
# edición fluida y respirable, ~2 trozos de subtítulo por corte, varios
# clips por escena, nunca un solo clip estirado —, transiciones suaves
# (fundidos de 0.4-0.5 s en los bordes del corte) y cama musical
# discreta SOLO de librería libre registrada (assets/music/manifest.json).
# Los clips viven en assets/footage/<tema>/ con manifest.json de procedencia
# (archivo, rol(es), fuente, URL de origen, licencia, autor, dimensiones,
# duración). Sin manifiesto válido, el render FALLA con mensaje claro.
FOOTAGE_ROOT = ROOT_DIR / "assets" / "footage"
MUSIC_ROOT = ROOT_DIR / "assets" / "music"
TITULAR_MAX_WORDS = 5

def footage_theme(script: dict):
    f = script.get("footage") or {}
    if f.get("theme"):
        return f["theme"]
    return real_theme(script)

def footage_dir(script: dict) -> Path:
    f = script.get("footage") or {}
    if f.get("dir"):
        p = Path(f["dir"])
        return p if p.is_absolute() else ROOT_DIR / p
    return FOOTAGE_ROOT / (footage_theme(script) or "")

def load_footage_manifest(script: dict):
    """(directorio, datos) o (directorio, None) si no hay manifiesto de metraje."""
    import json
    d = footage_dir(script)
    f = script.get("footage") or {}
    if f.get("manifest"):
        p = Path(f["manifest"])
        mf = p if p.is_absolute() else ROOT_DIR / p
        d = mf.parent
    else:
        mf = d / "manifest.json"
    if not mf.exists():
        return d, None
    try:
        return d, json.loads(mf.read_text(encoding="utf-8"))
    except Exception:
        return d, None

def _clip_roles(entry: dict) -> list:
    roles = entry.get("roles")
    if isinstance(roles, list) and roles:
        return [str(r) for r in roles]
    r = entry.get("role") or entry.get("rol")
    return [str(r)] if r else []

def _clip_entry_view(d: Path, entry: dict) -> dict:
    f = _entry_get(entry, "file", "archivo")
    path = Path(f) if f and Path(f).is_absolute() else d / f
    return {"path": path, "file": f, "roles": _clip_roles(entry),
            "source": _entry_get(entry, "source", "fuente"),
            "source_url": _entry_get(entry, "source_url", "url_origen"),
            "license": _entry_get(entry, "license", "licencia"),
            "author": _entry_get(entry, "author", "autor"),
            "crop_centering": entry.get("crop_centering"),
            "manifest_dimensions": entry.get("dimensions") or entry.get("dimensiones"),
            "manifest_duration": entry.get("duration_sec") or entry.get("duracion_sec")}

def assign_footage(script: dict):
    """Clips candidatos por escena (varios por rol: la edición corta cada
    4-6 s rotando clips y offsets). Devuelve (asignaciones, fallos):
    asignaciones[i] = lista de vistas de clip para la escena i."""
    scenes = effective_scenes(script)
    d, data = load_footage_manifest(script)
    if data is None:
        return [[] for _ in scenes], [f"sin manifiesto de metraje real en {d} "
                                      "(assets/footage/<tema>/manifest.json con procedencia y licencia es obligatorio)"]
    entries = data.get("clips") or data.get("scenes") or []
    views = [_clip_entry_view(d, e) for e in entries]
    fails, out = [], []
    for i, sc in enumerate(scenes):
        role = sc.get("image_role") or ROLE_AFFINITY.get(sc.get("icon", ""))
        cands = [v for v in views if role in v["roles"]]
        if not cands:
            fails.append(f"escena {i + 1}: sin clips de metraje para el rol {role!r}")
        out.append(cands)
    return out, fails

def titular_words(text: str) -> list:
    return [w for w in (text or "").replace("·", " ").split() if w]

def scene_titular(scene: dict) -> str:
    return (scene.get("titular") or "").strip()

def validate_footage(script: dict) -> list[str]:
    """Puertas del formato metraje_real (las usa automation/qc.py): manifiesto
    de clips con procedencia completa (fuente + URL de origen + licencia +
    autor), archivos existentes cuyas dimensiones y duración REALES (ffprobe)
    coinciden con el manifiesto, al menos 1 clip por rol de escena y al menos
    3 clips distintos por tema (la edición corta cada 4-6 s rotando clips), y
    titular corto (<=5 palabras) por escena que cabe medido con PIL."""
    import subprocess, json as _json
    from PIL import Image, ImageDraw
    dr = ImageDraw.Draw(Image.new("RGB", (W, H)))
    d, data = load_footage_manifest(script)
    fails = []
    if data is not None:
        fmt = str(data.get("format") or data.get("formato") or "metraje_real")
        if fmt != "metraje_real":
            fails.append(f"el manifiesto de {d} declara format={fmt!r}, no 'metraje_real'")
    assigns, afails = assign_footage(script)
    fails += list(afails)
    if data is not None:
        entries = data.get("clips") or data.get("scenes") or []
        if len(entries) < 3:
            fails.append(f"librería de metraje con {len(entries)} clip(s) (<3): la edición de cortes "
                         "cada 4-6 s exige varios clips por tema, no un solo clip estirado")
        for e in entries:
            v = _clip_entry_view(d, e)
            tag = v["file"] or "?"
            if not str(v["source"]).strip():
                fails.append(f"clip {tag!r}: sin fuente en el manifiesto")
            if not str(v["source_url"]).startswith("http"):
                fails.append(f"clip {tag!r}: sin URL de origen válida en el manifiesto")
            if not str(v["license"]).strip():
                fails.append(f"clip {tag!r}: sin licencia en el manifiesto")
            if not str(v["author"]).strip():
                fails.append(f"clip {tag!r}: sin autor en el manifiesto")
            p = v["path"]
            if not p.exists():
                fails.append(f"clip {tag!r}: no existe el archivo {p}")
                continue
            try:
                pr = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                     "stream=width,height", "-show_entries", "format=duration",
                                     "-of", "json", str(p)], capture_output=True, text=True)
                info = _json.loads(pr.stdout or "{}")
                st = (info.get("streams") or [{}])[0]
                w, h = st.get("width", 0), st.get("height", 0)
                dur = float((info.get("format") or {}).get("duration") or 0)
                if w < 1080 or h < 1920:
                    fails.append(f"clip {tag!r}: resolución {w}x{h} insuficiente para vertical 1080x1920")
                md = v.get("manifest_dimensions")
                if md:
                    if isinstance(md, dict):
                        mw, mh = md.get("width"), md.get("height")
                    else:
                        parts = str(md).lower().split("x")
                        mw, mh = (int(parts[0]), int(parts[1])) if len(parts) == 2 else (None, None)
                    if (mw, mh) != (w, h):
                        fails.append(f"clip {tag!r}: dimensiones del manifiesto ({mw}x{mh}) != archivo ({w}x{h})")
                mdu = v.get("manifest_duration")
                if mdu is not None and abs(float(mdu) - dur) > 1.5:
                    fails.append(f"clip {tag!r}: duración del manifiesto ({mdu}s) != archivo ({dur:.2f}s)")
            except Exception as ex:
                fails.append(f"clip {tag!r}: ffprobe falló: {ex}")
    for i, sc in enumerate(effective_scenes(script)):
        tit = scene_titular(sc)
        if not tit:
            fails.append(f"escena {i + 1}: sin titular corto (el estándar pone SOLO titulares del guión sobre el video)")
        elif len(titular_words(tit)) > TITULAR_MAX_WORDS:
            fails.append(f"escena {i + 1}: titular de {len(titular_words(tit))} palabras (>5): {tit!r}")
        else:
            try: fit_font_size(dr, tit.upper(), TEXT_MAX_W, 170, 56)
            except LayoutError as ex: fails.append(f"escena {i + 1} titular: {ex}")
    return fails

def make_footage_overlay(script: dict, scene_idx: int, caption_text: str):
    """Overlay RGBA 1080x1920 de UN segmento del formato metraje_real:
    degradado suave (legibilidad), pastilla de kicker en la zona superior,
    TITULAR CORTO de la escena en la franja del dato (58-72%) sobre pastilla
    semitransparente y subtítulo completo SOLO en la zona inferior.
    Nada más va sobre el video: ni el dato grande viejo, ni el apoyo, ni el
    título completo (ese vive solo en los metadatos)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ov = Image.new("L", (1, H))
    px = []
    for y in range(H):
        if y < ZONE_TOP[1]:
            a = int(150 * (1 - y / ZONE_TOP[1]))
        elif y < 900:
            a = 0
        else:
            a = int(190 * (y - 900) / (H - 900))
        px.append(a)
    ov.putdata(px)
    grad = Image.new("RGBA", (W, H), (7, 19, 12, 255))
    img = Image.composite(grad, img, ov.resize((W, H)))
    d = ImageDraw.Draw(img, "RGBA")
    _draw_kicker(d, script.get("kicker", ""))
    scenes = effective_scenes(script)
    sc = scenes[min(scene_idx, len(scenes) - 1)] if scenes else {}
    tit = scene_titular(sc).upper()
    if tit:
        size = fit_font_size(d, tit, TEXT_MAX_W, 170, 56)
        bb = d.textbbox((0, 0), tit, font=font(size))
        th = bb[3] - bb[1]
        band_h = ZONE_DATA[1] - ZONE_DATA[0]
        pad = 30
        py0 = ZONE_DATA[0] + (band_h - (th + 2 * pad)) / 2
        d.rounded_rectangle([36, py0, W - 36, py0 + th + 2 * pad], radius=30,
                            fill=(5, 15, 9, 205))
        color = GOLD if any(c.isdigit() for c in tit) else WHITE
        tw = text_w(d, tit, size)
        d.text(((W - tw) / 2, py0 + pad - bb[1]), tit, font=font(size), fill=color)
    # Subtítulo completo en su zona (misma regla que caption_overlay).
    size = 60
    lines = wrap_measured(d, caption_text, size, TEXT_MAX_W)
    if len(lines) > 2: raise LayoutError(f"subtítulo de {len(lines)} líneas: {caption_text!r}")
    lh = 76
    tw = max(text_w(d, ln, size) for ln in lines)
    pw, ph = tw + 64, len(lines) * lh + 44
    zone_h = ZONE_SUB[1] - ZONE_SUB[0]
    if ph > zone_h: raise LayoutError("pastilla de subtítulo más alta que su zona")
    x0 = (W - pw) / 2; y0 = ZONE_SUB[0] + (zone_h - ph) / 2
    d.rounded_rectangle([x0, y0, x0 + pw, y0 + ph], radius=28, fill=(0, 0, 0, 178))
    y = y0 + 22
    for ln in lines:
        lw = text_w(d, ln, size)
        bbox = d.textbbox((0, 0), ln, font=font(size))
        d.text(((W - lw) / 2, y - bbox[1]), ln, font=font(size), fill=WHITE)
        y += lh
    return img

def make_closing_card(emblem_path, title: str, line: str):
    """Tarjeta de cierre del canal (~2.5 s): fondo verde oscuro de marca,
    emblema vigente (branding/avatar-v2.png, medallón dorado recortado en
    círculo para que fusione con el fondo), nombre del canal y línea de
    seguimiento. Todo medido con PIL antes de dibujar."""
    from PIL import Image, ImageDraw, ImageOps
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, ZONE_TOP[1] - 3, W, ZONE_TOP[1]], fill=PANEL_SOFT)
    size_emb = 620
    try:
        emb = Image.open(emblem_path).convert("RGB")
        emb = ImageOps.fit(emb, (size_emb, size_emb))
        mask = Image.new("L", (size_emb, size_emb), 0)
        md = ImageDraw.Draw(mask)
        md.ellipse([10, 10, size_emb - 10, size_emb - 10], fill=255)
        img.paste(emb, ((W - size_emb) // 2, 300), mask)
    except Exception:
        d.ellipse([(W - size_emb) / 2, 300, (W + size_emb) / 2, 300 + size_emb],
                  outline=GOLD, width=6)
    d.rectangle([(W - 160) / 2, 990, (W + 160) / 2, 1000], fill=GOLD)
    t = (title or "Your Channel").upper()
    tsize = fit_font_size(d, t, TEXT_MAX_W, 104, 48)
    lines = wrap_measured(d, t, tsize, TEXT_MAX_W)
    if len(lines) > 2:
        tsize = fit_font_size(d, t, TEXT_MAX_W, 84, 40)
        lines = wrap_measured(d, t, tsize, TEXT_MAX_W)
    y = 1075
    for ln in lines:
        tw = text_w(d, ln, tsize)
        d.text(((W - tw) / 2, y), ln, font=font(tsize), fill=WHITE)
        y += int(tsize * 1.18)
    ln_text = (line or "").strip()
    if ln_text:
        lsize = fit_font_size(d, ln_text, TEXT_MAX_W, 56, 34)
        tw = text_w(d, ln_text, lsize)
        d.text(((W - tw) / 2, y + 36), ln_text, font=font(lsize), fill=GOLD)
    return img

def load_music_track():
    """Primera pista de la librería libre registrada (assets/music/manifest.json)
    cuyo archivo existe: dict con path y procedencia, o None. La cama musical
    es opcional; SIN licencia clara registrada no hay música (MANDATO §3d)."""
    import json
    mf = MUSIC_ROOT / "manifest.json"
    if not mf.exists():
        return None
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except Exception:
        return None
    for t in data.get("tracks") or []:
        f = t.get("file")
        if not f:
            continue
        p = Path(f) if Path(f).is_absolute() else MUSIC_ROOT / f
        if p.exists():
            return {"path": p, "file": f, "title": t.get("title", ""),
                    "author": t.get("author", ""), "source": t.get("source", ""),
                    "source_url": t.get("source_url", ""), "license": t.get("license", ""),
                    "attribution": t.get("attribution", "")}
    return None

