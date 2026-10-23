#!/usr/bin/env python3
"""
report.py — Reporte semanal en español para el dueño -> reports/reporte-<fecha>.md

Lee SOLO resúmenes (state.json, colas, QC, analytics.csv): barato en tokens y
sin intervención del dueño (MANDATO.md). Incluye línea de DINERO (RPM estimado
del nicho, progreso YPP, distancia al primer pago) y línea de INTERCONEXIÓN
(piezas en ready/ y su bloque de recursos gratis, siempre sin vender).
Uso: python3 automation/report.py
"""
import csv, json, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from common import load_json, load_config  # noqa: E402

def main():
    cfg = load_config(); targets = cfg.get("monetization_targets", {}) or {}
    state = load_json(ROOT / "automation" / "state.json", {})
    queue = load_json(ROOT / "content" / "queue.json", [])
    ready = sorted(p.name for p in (ROOT / "ready").glob("*") if p.is_dir())
    produced = sorted(p.parent.name for p in (ROOT / "output").glob("*/short.mp4"))
    qc_fails = [q["topic"] for q in queue if q.get("status") == "qc_failed"]
    pending = sum(1 for q in queue if q.get("status") == "pending")
    subs = views = hours = 0.0
    acsv = ROOT / "content" / "analytics.csv"
    if acsv.exists():
        rows = list(csv.DictReader(acsv.open(encoding="utf-8")))
        if rows:
            last = rows[-1]
            subs = float(last.get("subscribers") or last.get("subs") or 0); views = float(last.get("shorts_views_90d") or 0)
            hours = float(last.get("watch_hours_12m") or 0)
    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        import revenue_estimator as _re
        _rk = _re.ranking(); _me = _re.monthly_estimate(3, 1)
        _ranking_txt = "\n".join(
            f"- {r['subtema']}: ${r['ingreso_por_pieza_largo_base_usd']:.0f}/largo y ${r['ingreso_por_pieza_shorts_base_usd']:.2f}/Short (base ESTIMADO, RPM largo ${r['rpm_largo_base']:.0f})"
            for r in _rk)
        _ranking_txt += (f"\n- Estimación mensual al ritmo actual (ESTIMADO, canal monetizado): "
                         f"pesimista ${_me['pesimista']} · base ${_me['base']} · optimista ${_me['optimista']}.")
    except Exception as _e:
        _ranking_txt = f"- (estimador no disponible: {_e})"
    cuello = ("Crear el canal + OAuth del dueño (única acción humana pendiente)"
              if not state.get("checks", {}).get("oauth", {}).get("token")
              else "Conectar los placeholders de recursos gratis del ecosistema"
              if any("[RECURSO-GRATIS-" in (load_json(ROOT / "ready" / r / "metadata.json", {}).get("description", ""))
                     for r in ready)
              else "Producir el primer video largo (ruta 4.000 h)")
    _pub = load_json(ROOT / "content" / "published.json", [])
    _res = [r for r in _pub if "resumen" in str(r.get("slug", "")).lower()]
    _resumen_txt = (f"- Publicado: https://youtube.com/watch?v={_res[-1].get('youtube_video_id')} (enlazado al informe como manda el MANDATO)."
                    if _res else "- Aún sin publicar (no hay canal): guión del primer Resumen en `content/guiones-largos/02-resumen-semana-cola-fed-irs.md`; al publicarse, este informe lo enlaza automáticamente desde `content/published.json`.")
    inter = []
    for r in ready:
        meta = load_json(ROOT / "ready" / r / "metadata.json", {})
        tag = "recurso gratis del tema" if "Recursos gratis" in meta.get("description", "") else "sin bloque"
        fmt = "animado" if (ROOT / "ready" / r / "animated_manifest.json").exists() else "estándar"
        inter.append(f"  - ready/{r} [{fmt}]: bloque «Recursos gratis» + «Más de nuestro ecosistema» ({tag}, sin venta)")
    lines = f"""# Reporte semanal — Your Channel ({fecha})

## Producción
- Videos producidos (paquetes con Short renderizado): **{len(produced)}**
- En cola `ready/` (QC aprobado, esperando canal): **{len(ready)}**
- Temas pendientes en banco: **{pending}** · Rechazados por QC: **{len(qc_fails)}** {qc_fails if qc_fails else ''}
- Estado del sistema: healthy={state.get('healthy')} · modo conservador={state.get('conservative_mode')} · publicación bloqueada={state.get('publish_blocked')}

## Dinero y meta (con números)
- **Estado honesto hoy: revenue real = ${float(last.get("revenue_usd") or 0) if rows else 0:.2f}.** Sin canal creado y antes del Partner Program, YouTube no paga anuncios: $0 es la cifra real, no una estimación.
- **Meta de monetización (YPP completo):** 1.000 subs + UNA ruta: 10M vistas Shorts en 90 días O 4.000 horas públicas en 12 meses. **Primer pago AdSense al acumular $100.**
- **La matemática del ritmo (cadencia nueva 2026-10-20: 1 principal/día ≈ 90 piezas en 90 días + Shorts espejo de los largos semanales, hasta ~129 piezas):**
  - Ruta Shorts: 10.000.000 / 129 ≈ **77.500 vistas promedio por pieza** — en la práctica se llega por base creciente + piezas virales, no por promedio uniforme.
  - Ruta horas (la principal para cobrar): el largo semanal de 8-12 min suma 4.000 h = 240.000 minutos ≈ **48.000 vistas largas** a 5 min por vista; los Shorts son el embudo hacia el largo.
  - Subs: a 1-5 subs por cada 1.000 vistas, los 1.000 subs requieren ~200.000-1.000.000 de vistas acumuladas.
  - Primeros $100 tras monetizar: a RPM largo $15-20 ≈ **5.000-6.700 vistas largas**; a RPM Shorts $0.15-0.25/1.000 ≈ 400.000-670.000 vistas. Por eso el ingreso serio es el largo.
- **Hitos (meta interna, no promesa):** Día 30: canal publicado, ritmo de 1 principal/día + espejo sostenido y primeras métricas reales. Día 60: checkpoint de 500 subs (fan funding). Día 90: evaluación formal contra YPP con fecha proyectada calculada de los datos reales.

## Dinero (responsabilidad de Muse — MANDATO.md)
- RPM de referencia del nicho: Shorts {targets.get('niche_rpm_reference_usd', {}).get('shorts_per_1000', '0.15-0.25')} USD/1.000 · Largo {targets.get('niche_rpm_reference_usd', {}).get('long_per_1000', '10-22')} USD/1.000 (estimado del nicho, NO ingreso real todavía).
- Progreso YPP: **{subs:.0f} / 1.000 subs** · **{views:.0f} / 10.000.000 vistas Shorts (90 días)** · **{hours:.0f} / 4.000 h** de video largo.
- Distancia al primer pago AdSense: faltan {max(0, 1000 - subs):.0f} subs y completar una ruta de horas/vistas; sin canal creado aún, el ingreso real es $0 — la meta inmediata es la elegibilidad, no la cifra.

## Ranking por DINERO y pivote de la semana (estimado, no vistas)
{_ranking_txt}
- **Pivote aplicado:** la mezcla de la próxima semana se re-pesa hacia los 2 subtemas top por ingreso estimado por pieza (más slots diarios y el tema del largo), con la excepción de embudo del MANDATO: el subtema que trae los suscriptores no pierde su slot aunque rankee bajo en dinero.

## Interconexión sin vender (MANDATO.md)
{chr(10).join(inter) if inter else '  - Sin piezas en ready/ todavía.'}
- Regla aplicada: solo recursos gratuitos; prohibidos precios, checkout y pitch (el QC rechaza venta directa).

## Fallos y supervisión
- Última supervisión de Muse: {state.get('last_supervision_at', 'sin registrar')}
- Motivos registrados: {state.get('reasons', [])}

## Video «Resumen de la semana»
{_resumen_txt}

## Próximo cuello de botella
**{cuello}.**
"""
    out = ROOT / "reports" / f"reporte-{fecha}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(lines, encoding="utf-8")
    print(lines)
    print(f"[report] escrito en {out}")

if __name__ == "__main__":
    main()
