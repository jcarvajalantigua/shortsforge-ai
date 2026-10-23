#!/usr/bin/env python3
"""
title_thumbnail.py — Título (<60 caracteres), descripción con hashtags y portada.

Canal: Your Channel (finanzas/negocios + IA, hispanos en USA).
- Título: plantilla por tipo de tema, recortado a 59 caracteres como máximo.
- Descripción: resumen + disclaimer educativo + hashtags en español.
- Portada 1080x1920 con PIL: fondo del color de marca, texto grande, banda de
  acento y nombre del canal (config.yaml). Sin imágenes de terceros.

Uso:
    python3 tools/title_thumbnail.py --topic "..." --out-dir output/<slug>
Genera: metadata.json + cover.png dentro de out-dir.
"""
import argparse, json, sys, textwrap
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import load_config, save_json, slugify

HASHTAGS = ["#FinanzasPersonales", "#DineroEnUSA", "#Negocios", "#Shorts", "#CreditoUSA"]
TITLE_TEMPLATES = ["{t}", "En 60 segundos: {t}", "Ojo: {t}", "{t}"]

def make_title(topic: str) -> str:
    base = topic.strip().rstrip(".")
    for tpl in TITLE_TEMPLATES:
        cand = tpl.format(t=base)
        if len(cand) <= 59:
            return cand
    return base[:56].rstrip() + "..." if len(base) > 59 else base

def _resource_tag(topic: str) -> str:
    t = topic.lower()
    if any(k in t for k in ("tarjeta", "crédito", "credito", "puntaje", "deuda")):
        return "CREDITO"
    if any(k in t for k in ("impuesto", "llc", "ein", "1099", "w-9", "deduccion", "deducción")):
        return "IMPUESTOS"
    if any(k in t for k in ("ia", "inteligencia artificial", "automat")):
        return "IA"
    return "NEGOCIO"

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

def _fecha_larga(iso: str) -> str:
    try:
        y, m, d = (int(x) for x in iso.split("-"))
        return f"{d} de {MESES[m - 1]} de {y}"
    except Exception:
        return iso

def sources_block(news: dict | None) -> str:
    """Bloque OBLIGATORIO «Fuentes:» (orden del dueño 2026-10-20): nombre,
    fecha de la noticia y URL real, tomados del paquete (news.sources /
    news.source_url). Sin fuente con URL, el QC rechaza la pieza de actualidad."""
    if not news:
        return ""
    srcs = news.get("sources") or []
    if not srcs and news.get("source_url"):
        srcs = [{"name": news.get("fuente", ""), "url": news["source_url"],
                 "date": news.get("fecha_noticia", "")}]
    lines = []
    for s in srcs:
        if s.get("url"):
            lines.append(f"- {s.get('name', '')} — {_fecha_larga(s.get('date', ''))} — {s['url']}")
    return "Fuentes:\n" + "\n".join(lines) if lines else ""

def make_description(topic: str, script_summary: str = "", news: dict | None = None) -> str:
    # Bloques de interconexión SIN vender (MANDATO.md): solo recursos gratuitos.
    # Los placeholders se sustituyen por recursos reales tras crear el canal;
    # el QC (automation/qc.py) impide publicar con placeholders sin resolver.
    tag = _resource_tag(topic)
    lines = [topic.strip() + ".",
             script_summary.strip(),
             "Contenido educativo general para hispanos en Estados Unidos. No es asesoría financiera, fiscal ni legal personalizada: consulta tu caso con un profesional certificado.",
             sources_block(news),
             f"Recursos gratis sobre este tema:\n[RECURSO-GRATIS-{tag}]",
             "Más de nuestro ecosistema (recursos gratuitos):\n[ECOSISTEMA-RECURSO-GRATIS]",
             "Nuevo video cada día. Comenta tu caso (sin datos personales) y sigue el canal.",
             " ".join(HASHTAGS)]
    return "\n\n".join(x for x in lines if x)

def make_cover(topic: str, out_path: Path, cfg: dict):
    from PIL import Image, ImageDraw, ImageFont
    brand = cfg.get("branding", {}) if isinstance(cfg, dict) else {}
    chan = cfg.get("channel", {}) if isinstance(cfg, dict) else {}
    bg = brand.get("primary_color", "#0A1F14"); accent = brand.get("accent_color", "#1DB954")
    footer = (chan.get("proposed_name", "Your Channel") or "Your Channel").upper()
    img = Image.new("RGB", (1080, 1920), bg)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 1500, 1080, 1560], fill=accent)
    d.rectangle([0, 0, 1080, 24], fill=accent)
    def font(size):
        for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                  "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]:
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
        return ImageFont.load_default()
    # Título de la PORTADA medido con PIL (la portada es metadato, no fondo de
    # video): se envuelve por palabras y se reduce la fuente hasta que cada
    # línea cabe en 960 px — nunca se dibuja fuera de márgenes.
    words = topic.upper().split()
    size, lines = 110, []
    while size >= 52:
        f = font(size); lines, cur = [], ""
        for w_ in words:
            trial = f"{cur} {w_}".strip()
            if d.textlength(trial, font=f) <= 960: cur = trial
            else: lines.append(cur); cur = w_
        if cur: lines.append(cur)
        if len(lines) <= 5 and all(d.textlength(ln, font=f) <= 960 for ln in lines): break
        size -= 8
    f = font(size)
    y = 380
    for ln in lines:
        tw = d.textlength(ln, font=f)
        d.text(((1080 - tw) / 2, y), ln, font=f, fill="#FFFFFF")
        y += int(size * 1.22)
    f52 = font(52)
    tw = d.textlength(footer, font=f52)
    d.text((max(40, (1080 - tw) / 2), 1620), footer, font=f52, fill="#FFFFFF")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path

def build_package(topic: str, out_dir: Path, script_summary: str = "", news: dict | None = None) -> dict:
    cfg = load_config()
    title = make_title(topic)
    meta = {"title": title, "title_chars": len(title),
            "description": make_description(topic, script_summary, news),
            "tags": ["finanzas personales en español", "dinero en usa", "credito en usa",
                     "llc en español", "negocios hispanos", "ia para negocios",
                     "educacion financiera", "hispanos en usa"],
            "category_id": 27, "language": "es", "privacy_default": "private",
            "made_for_kids": False, "contains_copyrighted_footage": False,
            "slug": slugify(topic)}
    if news:
        meta["news"] = news  # fuente + fecha + URL(s): la descripción las lleva en «Fuentes:»
    cover = make_cover(topic, Path(out_dir) / "cover.png", cfg)
    meta["cover"] = str(cover)
    save_json(Path(out_dir) / "metadata.json", meta)
    return meta

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--summary", default="")
    args = ap.parse_args()
    print(json.dumps(build_package(args.topic, Path(args.out_dir), args.summary), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
