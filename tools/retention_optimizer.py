#!/usr/bin/env python3
"""
retention_optimizer.py — Optimización de retención en dos fases (RETENCION.md).

FASE ANTES (construye para retener): puntúa un guión/paquete 0-100:
  - Gancho 0-3 s (30 pts): pregunta, dato con número o promesa concreta en la
    primera frase; saludo/intro («hola», «bienvenidos») resta.
  - Ritmo (20 pts): >=5 segmentos (gancho + 3 bloques + cierre) y bloques
    cortos: un cambio de idea/visual cada ~5-7 s de narración.
  - Loop abierto (15 pts): el gancho plantea pregunta/promesa que solo se
    resuelve al final (marcadores + payoff en los bloques/cierre).
  - Cierre en loop (15 pts): el final conecta con el inicio (repite palabras
    clave del gancho o devuelve su pregunta) -> empuja replay del Short.
  - Duración (20 pts): Short objetivo 35-55 s (55-65 s parcial).
  Un Short con score < 70 NO pasa el QC a ready/ (automation/qc.py).

FASE DESPUÉS (aprende): lee métricas por pieza desde CSV de Analytics
(content/analytics.csv si tiene columnas de retención, o --csv de Studio)
y compara contra el promedio del canal: retención 3 s, % promedio visto,
% al final, CTR, subs/1.000 vistas, swipe-away. Produce recomendaciones en
reports/retention-<fecha>.md. Sin token de Analytics hoy: con --demo usa
datos de ejemplo y lo anota HONESTO en el reporte.
Además registra por pieza la CADENA DE PRUEBA del marco de alcance
(content/marco-alcance.md): `cadena_prueba()` — prueba inicial superada
sí/no según retención 3 s y % completado, con los campos replays /
interacciones / alcance_ampliado listos para cuando haya datos reales.

Uso:
    python3 tools/retention_optimizer.py --script content/scripts/<slug>.json
    python3 tools/retention_optimizer.py --package output/<slug>
    python3 tools/retention_optimizer.py --analyze [--demo] [--csv ruta.csv]
"""
import argparse, csv, json, re, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, CONTENT, load_json, slugify

GREETINGS = ("hola", "bienvenidos", "bienvenidas", "en este video", "en este vídeo", "qué tal")
PROMISE_MARKERS = ("te lo muestro", "te doy", "te enseño", "mira", "quédate", "quedate",
                   "al final", "la tercera", "la diferencia", "atención", "ojo")
PAYOFF_MARKERS = ("por eso", "la ventaja real", "la respuesta", "el resultado", "en resumen",
                  "la lección", "la clave", "atención al mito", "ahora mira")

def _first_sentence(text: str) -> str:
    m = re.split(r"(?<=[.?!])\s+", text.strip(), maxsplit=1)
    return m[0] if m else text[:120]

def score_script(script: dict) -> dict:
    text = script.get("full_text", "")
    sections = script.get("sections", {}) or {}
    hook = sections.get("hook_0_3s") or _first_sentence(text)
    blocks = sections.get("desarrollo") or []
    closing = sections.get("cierre_cta") or (text.rsplit(". ", 1)[-1] if text else "")
    secs = float(script.get("estimated_seconds") or (len(text.split()) / 155 * 60))
    motivos, score = [], 0
    # Gancho (30)
    h = hook.lower()
    if any(h.startswith(g) or f" {g}" in h[:24] for g in GREETINGS):
        motivos.append("gancho: empieza con saludo/intro — prohibido, se entra directo al tema")
    elif "¿" in hook or "?" in hook:
        score += 30; motivos.append("gancho: pregunta directa en 0-3 s (+30)")
    elif re.search(r"\d", hook):
        score += 28; motivos.append("gancho: dato con número en 0-3 s (+28)")
    elif any(m in h for m in PROMISE_MARKERS):
        score += 26; motivos.append("gancho: promesa concreta en 0-3 s (+26)")
    else:
        score += 10; motivos.append("gancho: sin pregunta, número ni promesa clara (+10) — reescribir")
    # Ritmo (20)
    n_seg = 1 + len(blocks) + (1 if closing else 0)
    long_blocks = [i for i, b in enumerate(blocks) if len(b.split()) > 50]
    if n_seg >= 5 and not long_blocks:
        score += 20; motivos.append(f"ritmo: {n_seg} segmentos, bloques cortos (+20)")
    elif n_seg >= 4:
        score += 14; motivos.append(f"ritmo: {n_seg} segmentos; bloques largos: {long_blocks or '—'} (+14)")
    else:
        score += 6; motivos.append(f"ritmo: solo {n_seg} segmentos — falta cambio de idea cada 5-7 s (+6)")
    # Loop abierto (15)
    early = (hook + " " + (blocks[0] if blocks else "")).lower()
    late = (" ".join(blocks[1:]) + " " + closing).lower()
    if ("¿" in hook or any(m in early for m in PROMISE_MARKERS)) and any(p in late for p in PAYOFF_MARKERS):
        score += 15; motivos.append("loop abierto: promesa/pregunta inicial con payoff al final (+15)")
    elif "¿" in hook or any(m in early for m in PROMISE_MARKERS):
        score += 10; motivos.append("loop abierto: hay promesa inicial, payoff débil (+10)")
    else:
        motivos.append("loop abierto: no se detecta — el espectador no tiene motivo para quedarse (0)")
    # Cierre en loop (15)
    stop = {"para", "como", "este", "esta", "esto", "tiene", "puede", "desde", "sobre", "cuando", "porque"}
    hook_words = {w for w in re.findall(r"[a-záéíóúñ]{4,}", h) if w not in stop}
    close_words = {w for w in re.findall(r"[a-záéíóúñ]{4,}", closing.lower()) if w not in stop}
    overlap = hook_words & close_words
    if "¿" in closing or "?" in closing:
        score += 15; motivos.append("cierre en loop: devuelve pregunta al espectador (+15)")
    elif len(overlap) >= 2:
        score += 13; motivos.append(f"cierre en loop: retoma el gancho ({', '.join(sorted(overlap)[:3])}) (+13)")
    elif len(overlap) == 1:
        score += 8; motivos.append("cierre en loop: conexión débil con el inicio (+8)")
    else:
        motivos.append("cierre en loop: no conecta con el inicio — se pierde el replay (0)")
    # Duración (20)
    if 35 <= secs <= 55:
        score += 20; motivos.append(f"duración: {secs:.0f} s en objetivo 35-55 (+20)")
    elif 55 < secs <= 65 or 28 <= secs < 35:
        score += 12; motivos.append(f"duración: {secs:.0f} s fuera del óptimo pero aceptable (+12)")
    else:
        score += 4; motivos.append(f"duración: {secs:.0f} s — objetivo Short 35-55 s (+4)")
    return {"score": score, "passes_qc": score >= 70, "estimated_seconds": secs,
            "motivos": motivos, "hook": hook}

def cadena_prueba(row: dict) -> dict:
    """CADENA DE PRUEBA del algoritmo (content/marco-alcance.md): prueba
    inicial → retención alta → replays → interacciones → ampliación.
    Con los datos que Analytics entrega hoy (retención 3 s y % completado,
    ver RETENCION.md) se evalúa la PUERTA de la prueba inicial: superada si
    ret3s >= 70% y % completado >= 60%. «replays», «interacciones» y
    «alcance_ampliado» quedan como campos del registro, listos para cuando
    el CSV/API los traiga (hoy: None = aún sin dato, NUNCA un cero falso)."""
    ret3s, fin = row.get("ret3s"), row.get("pct_final")
    base = {"retencion_3s": ret3s, "pct_completado": fin,
            "replays": row.get("replays"), "interacciones": row.get("interacciones"),
            "alcance_ampliado": row.get("alcance_ampliado")}
    if ret3s is None:
        return {"prueba_inicial_superada": None, "etapa_fallo": "sin_datos", **base}
    ok = ret3s >= 70 and (fin is None or fin >= 60)
    etapa = None if ok else ("retencion_3s" if ret3s < 70 else "completado")
    return {"prueba_inicial_superada": ok, "etapa_fallo": etapa, **base}

def analyze(rows: list[dict], demo: bool) -> Path:
    def avg(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else 0.0
    a = {k: avg(k) for k in ("ret3s", "pct_visto", "pct_final", "ctr", "subs_1000", "swipe")}
    recs, cadenas = [], {}
    for r in rows:
        tag = "duplicar" if (r.get("ret3s", 0) >= a["ret3s"] and r.get("pct_final", 0) >= a["pct_final"]) else \
              ("cortar/reformular" if r.get("ret3s", 0) < a["ret3s"] * 0.7 else "mantener")
        cp = cadena_prueba(r)  # marco de alcance: cadena de prueba por pieza
        cadenas[r["pieza"]] = cp
        estado = ("cadena de prueba: SIN DATOS aún" if cp["prueba_inicial_superada"] is None else
                  "cadena de prueba: prueba inicial SUPERADA" if cp["prueba_inicial_superada"] else
                  f"cadena de prueba: descartada en la prueba inicial (falla: {cp['etapa_fallo']})")
        recs.append(f"- **{r['pieza']}**: retención 3 s {r.get('ret3s')}%, final {r.get('pct_final')}% → {tag}. {estado}.")
    glob = []
    if a["ret3s"] and a["ret3s"] < 70: glob.append("- Retención 3 s del canal <70%: reescribir el TIPO de gancho de la próxima tanda (pregunta > dato > promesa).")
    if a["pct_final"] and a["pct_final"] < 60: glob.append("- Completado <60%: acortar Shorts hacia 40-45 s y adelantar el payoff.")
    if a["ctr"] and a["ctr"] < 4 and a["ret3s"] >= 70: glob.append("- CTR bajo con retención buena: el problema es título/portada, no el video — probar 2 títulos por tema.")
    if a["subs_1000"] and a["subs_1000"] < 1: glob.append("- Subs/1.000 vistas <1: reforzar el cierre en loop y la promesa de serie («cada día, un tema»).")
    if not glob: glob.append("- Sin alertas globales: mantener fórmula y escalar el tema ganador.")
    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = ROOT / "reports" / f"retention-{fecha}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    nota = ("**Datos DEMO** (sin token de YouTube Analytics todavía): estructura y umbrales reales, "
            "cifras de ejemplo para validar el flujo." if demo else
            "**Datos del CSV** indicado (export de YouTube Studio / Analytics API).")
    out.write_text(f"""# Retención — análisis {fecha}

{nota}

## Promedios del canal (según las piezas analizadas)
| Retención 3 s | % visto | % al final | CTR | Subs/1.000 | Swipe-away |
|---|---|---|---|---|---|
| {a['ret3s']}% | {a['pct_visto']}% | {a['pct_final']}% | {a['ctr']}% | {a['subs_1000']} | {a['swipe']}% |

## Por pieza (contra el promedio)
{chr(10).join(recs)}

## Recomendaciones del ciclo semanal de Muse
{chr(10).join(glob)}
- Aplicar los ajustes a las PLANTILLAS (script_generator) y a la siguiente tanda, sin intervención del dueño (RETENCION.md).

## Registro de la cadena de prueba por pieza (marco de alcance)

Estructura fija por pieza publicada: `prueba_inicial_superada` (sí/no según
retención 3 s >= 70% y % completado >= 60%), `etapa_fallo`, y los campos
`replays` / `interacciones` / `alcance_ampliado` (null = Analytics aún no
los entrega; se rellenan cuando el CSV/API los traiga).

```json
{json.dumps(cadenas, ensure_ascii=False, indent=2)}
```
""", encoding="utf-8")
    return out

DEMO_ROWS = [
    {"pieza": "demo-tarjeta-pago-minimo", "ret3s": 74, "pct_visto": 81, "pct_final": 63, "ctr": 5.1, "subs_1000": 2.4, "swipe": 31},
    {"pieza": "demo-llc-o-tu-nombre", "ret3s": 58, "pct_visto": 64, "pct_final": 41, "ctr": 3.2, "subs_1000": 0.8, "swipe": 47},
    {"pieza": "demo-ia-gratis-negocio", "ret3s": 69, "pct_visto": 77, "pct_final": 57, "ctr": 4.4, "subs_1000": 1.9, "swipe": 36},
]

def _rows_from_csv(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            def num(*names):
                for n in names:
                    if raw.get(n) not in (None, ""):
                        try: return float(str(raw[n]).replace("%", ""))
                        except Exception: pass
                return None
            rows.append({"pieza": raw.get("pieza") or raw.get("title") or raw.get("Video title") or "pieza",
                         "ret3s": num("ret3s", "retencion_3s"), "pct_visto": num("pct_visto", "average_percentage_viewed"),
                         "pct_final": num("pct_final"), "ctr": num("ctr", "impressions_ctr"),
                         "subs_1000": num("subs_1000"), "swipe": num("swipe", "swipe_away"),
                         # Cadena de prueba (marco de alcance): columnas opcionales del CSV;
                         # si no vienen, quedan None (sin dato), nunca cero.
                         "replays": num("replays"), "interacciones": num("interacciones"),
                         "alcance_ampliado": num("alcance_ampliado")})
    return [r for r in rows if r["ret3s"] is not None]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script"); ap.add_argument("--package")
    ap.add_argument("--analyze", action="store_true"); ap.add_argument("--demo", action="store_true")
    ap.add_argument("--csv")
    args = ap.parse_args()
    if args.script or args.package:
        if args.package:
            man = load_json(Path(args.package) / "package_manifest.json", {})
            spath = man.get("script") or ""
            script = load_json(spath, {}) if spath else {}
            if not script:
                print(json.dumps({"error": "paquete sin guión enlazado en el manifiesto"})); sys.exit(1)
        else:
            script = load_json(args.script, {})
        print(json.dumps(score_script(script), ensure_ascii=False, indent=2)); return
    if args.analyze:
        rows, demo = [], bool(args.demo)
        if args.csv:
            rows = _rows_from_csv(Path(args.csv))
        if not rows and (CONTENT / "analytics.csv").exists():
            rows = _rows_from_csv(CONTENT / "analytics.csv")
        if not rows:
            rows, demo = DEMO_ROWS, True
        out = analyze(rows, demo)
        print(json.dumps({"report": str(out), "demo": demo, "pieces": len(rows)}, ensure_ascii=False, indent=2)); return
    ap.error("usa --script, --package o --analyze")

if __name__ == "__main__":
    main()
