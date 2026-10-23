#!/usr/bin/env python3
"""
trend_finder.py — Busca temas del canal (RSS + actualidad verificada + evergreen).

- Intenta leer los RSS de config.yaml (Fed, Investopedia, WSJ Personal Finance).
- Si no hay red o un feed falla, NO se cae: suma la actualidad VERIFICADA por
  Muse (content/temas-actualidad.json, fuente+fecha) y el banco evergreen
  (content/temas-30-finanzas.json + content/temas-mixtos.json).
- Puntúa: novedad (fecha RSS), términos del nicho, tipo de tema.
- MEZCLA EDITORIAL (MANDATO §1d): cada candidato lleva su categoría de mezcla
  (dinero-finanzas 40 / ia-tecnologia 30 / negocios 20 / vida-practica-alto-
  valor 10, de config.yaml) y la selección rota por DÉFICIT de categoría
  contra la cola pendiente: no todo puede ser dinero.
- Deduplica contra content/queue.json y content/seen_topics.json (por slug).
- Guarda el resultado en content/queue.json con estado "pending".

Uso:
    python3 tools/trend_finder.py [--max 10] [--offline]
Salida: JSON por stdout con los temas añadidos.
NO descarga videos ni contenido con copyright: solo titulares/temas.
"""
import argparse, json, re, sys, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import (ROOT, CONTENT, QUEUE_FILE, SEEN_FILE, load_json, save_json,
                    slugify, load_config, mix_category, mix_pcts, mix_deficits)

KNOWN_TERMS = ["credito", "crédito", "tarjeta", "deuda", "llc", "impuestos", "irs",
               "puntaje", "ahorro", "negocio", "emprender", "inteligencia artificial", "ia",
               "cuenta", "banco", "interes", "interés", "presupuesto", "dinero",
               "hipoteca", "inversion", "inversión", "invertir", "seguro", "salud",
               "jubilacion", "jubilación", "retiro", "automatizacion", "automatización",
               "software", "ventas", "contratar", "nomina", "nómina", "casa", "vivienda"]

# Clasificación de titulares RSS a categoría de mezcla (la actualidad del pool
# verificado trae su categoría explícita; esto es solo para titulares sueltos).
_NEWS_CAT_KEYWORDS = [
    ("ia-tecnologia", ["inteligencia artificial", " ia ", "chatgpt", "openai", "software",
                       "automatiz", "tecnolog", "app ", "robot"]),
    ("vida-practica-alto-valor", ["medicare", "seguro de salud", "health insurance", "salud",
                                  "jubilac", "retiro", "retirement", "social security",
                                  "seguro social", "vivienda", "housing", "renta", "alquiler"]),
    ("negocios", ["small business", "negocio", "emprendedor", "emprend", "llc", "empleo",
                  "trabajo", "jobs", "contrat", "ventas", "empresa"]),
    ("dinero-finanzas", ["fed", "tasa", "inflacion", "inflación", "irs", "impuesto", "tax",
                         "credito", "crédito", "tarjeta", "deuda", "ahorro", "invers",
                         "hipoteca", "mortgage", "banco", "dinero", "bolsa", "mercado"]),
]

def classify_news_title(title: str) -> str:
    t = f" {title.lower()} "
    for cat, kws in _NEWS_CAT_KEYWORDS:
        if any(k in t for k in kws):
            return cat
    return "dinero-finanzas"

def score_item(title: str, pub_ts: float | None) -> int:
    s, t = 10, title.lower()
    if any(f in t for f in KNOWN_TERMS):
        s += 25
    for kw, pts in [("error", 10), ("gratis", 8), ("guia", 8), ("guía", 8),
                    ("como", 5), ("cómo", 5), ("impuestos", 10), ("credito", 10),
                    ("crédito", 10), ("llc", 10), ("ahorro", 7), ("deuda", 8)]:
        if kw in t:
            s += pts
    if pub_ts:  # novedad: hasta +30 si es de las últimas 24 h
        age_h = max(0.0, (datetime.now(timezone.utc).timestamp() - pub_ts) / 3600)
        s += max(0, int(30 - age_h))
    return s

def fetch_rss(url: str, timeout: int = 12) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; OctagonoEn60/1.0)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        root = ET.fromstring(r.read())
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        pub_ts = None
        raw = item.findtext("pubDate") or ""
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
            try:
                pub_ts = datetime.strptime(raw.strip(), fmt).timestamp(); break
            except Exception:
                pass
        if title:
            out.append({"topic": title, "source": url, "kind": "noticia", "pub_ts": pub_ts})
    return out

def actualidad_seed() -> list[dict]:
    """Actualidad VERIFICADA por Muse (content/temas-actualidad.json):
    cada tema trae fuente y fecha; >7 días no entra (vigencia_dias)."""
    from datetime import date
    temas = load_json(CONTENT / "temas-actualidad.json", [])
    hoy = date.today()
    out = []
    for t in temas:
        try:
            f = date.fromisoformat(t.get("fecha_noticia", "2000-01-01"))
            if (hoy - f).days > int(t.get("vigencia_dias", 7)):
                continue
        except Exception:
            continue
        out.append({"topic": t["tema"], "source": t.get("fuente", "actualidad-verificada"),
                    "kind": "actualidad", "angle": t.get("dato_clave", ""), "pub_ts": None,
                    "categoria": mix_category("actualidad", t.get("categoria") or t.get("categoria_mezcla")),
                    "fecha_noticia": t.get("fecha_noticia", "")})
    return out

def evergreen_seed() -> list[dict]:
    """Banco evergreen completo: temas-30-finanzas.json + temas-mixtos.json
    (pool de la mezcla editorial §1d: negocios, IA/tecnología y vida práctica
    de alto valor, cada tema con su categoria_mezcla y justificación)."""
    temas = load_json(CONTENT / "temas-30-finanzas.json", []) or load_json(CONTENT / "temas-30.json", [])
    temas = temas + load_json(CONTENT / "temas-mixtos.json", [])
    return [{"topic": t["tema"], "source": "banco-evergreen", "kind": t.get("tipo", "evergreen"),
             "angle": t.get("angulo") or t.get("gancho", ""), "pub_ts": None,
             "categoria": mix_category(t.get("tipo"), t.get("categoria_mezcla") or t.get("categoria"))}
            for t in temas]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=10)
    ap.add_argument("--offline", action="store_true", help="Saltar RSS y usar solo el banco evergreen")
    args = ap.parse_args()
    cfg = load_config()
    candidates = []
    if not args.offline:
        for url in cfg.get("sources_rss", []) if isinstance(cfg, dict) else []:
            try:
                candidates += fetch_rss(str(url))
            except Exception as e:
                print(f"[trend_finder] RSS falló ({url}): {e}", file=sys.stderr)
    candidates += actualidad_seed()
    candidates += evergreen_seed()
    queue = load_json(QUEUE_FILE, [])
    seen = set(load_json(SEEN_FILE, [])) | {q["slug"] for q in queue}
    # Regla del dueño (02:46 EDT): actualidad SIEMPRE primero. Evergreen =
    # colchón: máx 1 de cada 3 piezas SI hay actualidad nueva disponible;
    # sin actualidad nueva, el evergreen rellena todo (emergencia/conservador).
    def es_news(c): return c.get("kind") in ("actualidad", "noticia")
    # Categoría de mezcla de cada candidato (§1d): la actualidad verificada y
    # el evergreen la traen de su pool; los titulares RSS se clasifican por
    # palabras clave de alto valor.
    for c in candidates:
        if not c.get("categoria"):
            c["categoria"] = (classify_news_title(c["topic"]) if c.get("kind") == "noticia"
                              else mix_category(c.get("kind")))
    fresh = []
    for c in candidates:
        slug_c = slugify(re.sub(r"[^a-zA-ZáéíóúñÁÉÍÓÚÑ0-9 ]", "", c["topic"]))
        if slug_c not in seen:
            fresh.append(c)
    hay_news = any(es_news(c) for c in fresh)
    max_evergreen = max(1, args.max // 3) if hay_news else args.max
    # ROTACIÓN POR DÉFICIT (§1d): la base es la mezcla ya pendiente en cola;
    # en cada paso se elige primero la ACTUALIDAD (regla del dueño) y, dentro
    # del nivel, el candidato cuya categoría esté más por debajo de su %
    # objetivo (desempate: mayor score). Así la cola no se llena de dinero.
    pcts = mix_pcts(cfg if isinstance(cfg, dict) else None)
    counts = {}
    for q in queue:
        if q.get("status") == "pending":
            cat = mix_category(q.get("kind"), q.get("categoria_mezcla") or q.get("categoria"))
            counts[cat] = counts.get(cat, 0) + 1
    added, n_ev = [], 0
    pool = list(fresh)
    while pool and len(added) < args.max:
        deficits = mix_deficits(counts, pcts)
        news_pool = [c for c in pool if es_news(c)]
        ev_pool = [c for c in pool if not es_news(c)] if n_ev < max_evergreen else []
        tier = news_pool or ev_pool
        if not tier:
            break
        c = max(tier, key=lambda x: (deficits.get(x["categoria"], 0),
                                     score_item(x["topic"], x.get("pub_ts"))))
        pool.remove(c)
        if not es_news(c):
            n_ev += 1
        slug = slugify(re.sub(r"[^a-zA-ZáéíóúñÁÉÍÓÚÑ0-9 ]", "", c["topic"]))
        seen.add(slug)
        counts[c["categoria"]] = counts.get(c["categoria"], 0) + 1
        entry = {"slug": slug, "topic": c["topic"], "kind": c.get("kind", "evergreen"),
                 "angle": c.get("angle", ""), "source": c["source"],
                 "categoria_mezcla": c["categoria"],
                 "score": score_item(c["topic"], c.get("pub_ts")), "status": "pending",
                 "found_at": datetime.now(timezone.utc).isoformat()}
        if c.get("fecha_noticia"):
            entry["fecha_noticia"] = c["fecha_noticia"]
        if not es_news(c):
            entry["fallback_evergreen"] = True  # colchón marcado como tal
        queue.append(entry); added.append(entry)
    save_json(QUEUE_FILE, queue)
    save_json(SEEN_FILE, sorted(seen))
    print(json.dumps({"added": added, "queue_total": len(queue)}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
