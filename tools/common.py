"""Utilidades compartidas — canal YouTube en español (contenido original).

Desde el pivote 2026-10-20: Your Channel (finanzas/negocios + IA).
"""
import json, os, re, unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
OUTPUT = ROOT / "output"
QUEUE_FILE = CONTENT / "queue.json"
SEEN_FILE = CONTENT / "seen_topics.json"

def slugify(text: str, maxlen: int = 60) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t.lower()).strip("-")
    return t[:maxlen].strip("-") or "short"

def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default

def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def load_config(path=None):
    """Carga config.yaml con PyYAML si está; si no, parser mínimo clave: valor."""
    p = Path(path) if path else ROOT / "config.yaml"
    if not p.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        cfg = {}
        for line in p.read_text(encoding="utf-8").splitlines():
            if ":" in line and not line.startswith((" ", "#")):
                k, v = line.split(":", 1)
                cfg[k.strip()] = v.strip()
        return cfg

def estimate_seconds(word_count: int, wpm: int = 155) -> float:
    """Español narrado ~150-160 palabras/minuto."""
    return round(word_count / wpm * 60, 1)

# --- Mezcla editorial (MANDATO §1d; config.yaml -> editorial.mix) ---
# Orden del dueño 2026-10-20: contenido MIXTO, solo nichos de alto valor.
# Categorías canónicas de la mezcla y % objetivo por defecto (si config.yaml
# no cargara, la mezcla sigue existiendo: nunca se cae a «todo dinero»).
MIX_DEFAULT_PCT = {"dinero-finanzas": 40, "ia-tecnologia": 30,
                   "negocios": 20, "vida-practica-alto-valor": 10}
# Mapa tipo-de-tema (campo «tipo»/«kind» de los pools y la cola) -> categoría.
# Un tema puede sobreescribir su categoría con «categoria_mezcla» (pools) o
# «categoria»/«categoria_mezcla» (cola): el valor explícito siempre gana.
MIX_TIPO_MAP = {
    "credito": "dinero-finanzas", "llc-impuestos": "dinero-finanzas",
    "ahorro-cuentas": "dinero-finanzas", "inversion": "dinero-finanzas",
    "hipotecas": "dinero-finanzas", "errores": "dinero-finanzas",
    "ia-negocios": "ia-tecnologia", "ia-tecnologia": "ia-tecnologia",
    "negocios": "negocios", "historias": "negocios",
    "vida-practica": "vida-practica-alto-valor",
}

def mix_pcts(cfg: dict | None = None) -> dict:
    """% objetivo por categoría desde config.yaml (editorial.mix); con
    respaldo a MIX_DEFAULT_PCT. Devuelve {categoria: pct} sumando ~100."""
    if cfg is None:
        cfg = load_config()
    mix = ((cfg.get("editorial") or {}).get("mix") or {}) if isinstance(cfg, dict) else {}
    out = {}
    for cat, spec in mix.items():
        try:
            out[cat] = float((spec or {}).get("pct"))
        except Exception:
            continue
    return out or dict(MIX_DEFAULT_PCT)

def mix_category(tipo: str | None = None, explicit: str | None = None) -> str:
    """Categoría de mezcla de un tema. Gana el valor explícito; si no, el
    mapa por tipo; la actualidad sin clasificar y cualquier tipo desconocido
    caen a dinero-finanzas (el nicho histórico del canal)."""
    if explicit:
        return explicit
    if tipo in MIX_TIPO_MAP:
        return MIX_TIPO_MAP[tipo]
    return "dinero-finanzas"

def mix_deficits(counts: dict, pcts: dict | None = None) -> dict:
    """Déficit por categoría = % objetivo − % real en `counts` (conteo de
    piezas por categoría). Positivo = categoría atrasada (toca producirla);
    negativo = va pasada de su cuota. Base de la rotación por déficit."""
    pcts = pcts or mix_pcts()
    total = max(1, sum(counts.get(c, 0) for c in pcts))
    return {c: pcts[c] - 100.0 * counts.get(c, 0) / total for c in pcts}
