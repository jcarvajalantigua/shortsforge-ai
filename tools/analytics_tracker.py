#!/usr/bin/env python3
"""
analytics_tracker.py — Seguimiento manual/API del progreso al Partner Program.

Sin credenciales inventadas: el dueño (o YouTube Studio) aporta las cifras y
esta herramienta las registra en content/analytics.csv y calcula el progreso:
  - 1.000 suscriptores
  - 10.000.000 vistas de Shorts en 90 días   (ruta Shorts), o
  - 4.000 horas públicas en 12 meses         (ruta larga)

Uso:
    python3 tools/analytics_tracker.py --update --subs 120 --shorts-views-90d 450000 \
        --watch-hours 35 --published 21 [--date 2026-10-20]
    python3 tools/analytics_tracker.py --report
Opcional futuro: con YOUTUBE_API_KEY en el entorno se podría leer el canal,
pero el modo manual es la fuente oficial hasta conectar el OAuth del dueño.
"""
import argparse, csv, json, sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import CONTENT, load_config

CSV_FILE = CONTENT / "analytics.csv"
FIELDS = ["date", "subs", "shorts_views_90d", "watch_hours_12m", "published_shorts", "revenue_usd"]

def bar(pct: float, width: int = 24) -> str:
    filled = int(min(1.0, pct) * width)
    return "[" + "#" * filled + "-" * (width - filled) + f"] {pct*100:5.1f}%"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--date", default=str(date.today()))
    ap.add_argument("--subs", type=int, default=0)
    ap.add_argument("--shorts-views-90d", type=int, default=0)
    ap.add_argument("--watch-hours", type=float, default=0)
    ap.add_argument("--published", type=int, default=0)
    ap.add_argument("--revenue", type=float, default=0)
    args = ap.parse_args()
    if args.update:
        exists = CSV_FILE.exists()
        with CSV_FILE.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if not exists:
                w.writeheader()
            w.writerow({"date": args.date, "subs": args.subs, "shorts_views_90d": args.shorts_views_90d,
                        "watch_hours_12m": args.watch_hours, "published_shorts": args.published,
                        "revenue_usd": args.revenue})
        print(f"[analytics] fila registrada {args.date}")
    rows = list(csv.DictReader(CSV_FILE.open(encoding="utf-8"))) if CSV_FILE.exists() else []
    if args.report or args.update:
        if not rows:
            print("Sin datos todavía. Registra la primera fila con --update."); return
        last = rows[-1]
        cfg = load_config(); tgt = cfg.get("monetization_targets", {}) if isinstance(cfg, dict) else {}
        s_t = float(tgt.get("subscribers", 1000)); v_t = float(tgt.get("shorts_views_90d", 10_000_000)); h_t = float(tgt.get("watch_hours_12m", 4000))
        subs, views, hours = int(last["subs"]), int(last["shorts_views_90d"]), float(last["watch_hours_12m"])
        print(f"=== Progreso Partner Program ({last['date']}) ===")
        print(f"Suscriptores      {subs:>10,} / {int(s_t):,}   {bar(subs / s_t)}")
        print(f"Vistas Shorts 90d {views:>10,} / {int(v_t):,}   {bar(views / v_t)}")
        print(f"Horas 12m         {hours:>10,.0f} / {int(h_t):,}   {bar(hours / h_t)}")
        route = max(views / v_t, hours / h_t)
        print(f"Ruta más cercana: {'Shorts' if views / v_t >= hours / h_t else 'horas'} ({route*100:.1f}% del requisito de audiencia)")
        rev = float(last["revenue_usd"])
        print(f"Shorts publicados: {last['published_shorts']} | Ingresos registrados: ${rev:.2f}")
        print(f"\n=== DINERO Y META ===")
        print(f"Revenue real: ${rev:.2f} / $100 (primer pago AdSense)   {bar(rev / 100)}")
        if rev == 0:
            print("Estado honesto: $0 — antes del Partner Program (y sin canal creado) YouTube no paga anuncios.")
        print("Meta YPP: 1.000 subs + (10M vistas Shorts/90d O 4.000 h/12m). Primer pago al acumular $100.")
        print("Matemática del ritmo (cadencia 2026-10-20: 1 principal/día ≈ 90 piezas + espejo ≈ 129 piezas/90 días): ruta Shorts ≈ 77.500 vistas/pieza "
              "(se llega por base creciente + virales, no por promedio uniforme); ruta horas: 4.000 h = 240.000 min "
              "≈ 48.000 vistas largas a 5 min/vista — el largo manda y los Shorts son su embudo.")
        # Ritmo necesario vs real y fecha proyectada (solo con datos reales de >=2 filas)
        from datetime import date as _d, timedelta as _td
        proj = "sin datos aún (canal sin publicar)"
        if len(rows) >= 2 and subs > 0:
            try:
                d0 = _d.fromisoformat(rows[0]["date"]); d1 = _d.fromisoformat(last["date"])
                days = max(1, (d1 - d0).days)
                rate = (subs - int(rows[0]["subs"])) / days
                if rate > 0 and subs < s_t:
                    proj = str(d1 + _td(days=int((s_t - subs) / rate))) + f" (a {rate:.1f} subs/día)"
                elif subs >= s_t:
                    proj = "meta de subs alcanzada"
            except Exception:
                pass
        print(f"Fecha proyectada a 1.000 subs al ritmo actual: {proj}")
        if subs < s_t:
            print(f"Faltan {int(s_t) - subs} suscriptores. Revisa retención 3 s y CTR (RETENCION.md).")

if __name__ == "__main__":
    main()
