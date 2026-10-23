#!/usr/bin/env python3
"""
scheduler.py — Programación diaria según config.yaml (cadencia y horas).

No instala crons por sí solo: genera el plan del día y, con --emit-cron,
imprime las líneas de crontab LISTAS para que el dueño las apruebe e instale.
Cada corrida diaria hace: trend_finder -> run_pipeline (paquetes en privado).
La publicación nunca es automática: uploader.py es un paso humano aparte.

Uso:
    python3 tools/scheduler.py --plan          # muestra el plan de hoy
    python3 tools/scheduler.py --emit-cron     # líneas de crontab sugeridas
    python3 tools/scheduler.py --run-today --dry-run   # ejecuta el flujo del día en seco
"""
import argparse, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, load_config

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--emit-cron", action="store_true")
    ap.add_argument("--run-today", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    cad = cfg.get("cadence", {}) if isinstance(cfg, dict) else {}
    n = int(cad.get("shorts_per_day", 1) or 1)
    times = cad.get("publish_times_local", ["13:00"])
    if args.plan or not (args.emit_cron or args.run_today):
        print(f"Plan diario (cadencia 2026-10-20): {n} pieza principal/día (metraje_real) + Shorts espejo de los largos | pieza principal en la franja {times} ({cad.get('timezone','America/New_York')})")
        if cad.get("daily_mix"):
            print(f"Mezcla diaria: {cad['daily_mix']} | calendario oficial en YouTube: publishAt {times} {cad.get('timezone','America/New_York')}; el MP4 local se borra tras subir")
        if cad.get("long_videos_per_week"):
            print(f"Además: {cad['long_videos_per_week']} video largo (8-12 min) por semana — es la ruta de RPM alto; guiones en content/guiones-largos/")
            print(f"El largo semanal es el «Resumen de la semana» (noticias + lo más visto + lo más relevante), día sugerido: {cad.get('long_video_weekday', 'saturday')} (plantilla content/resumen-semanal.md)")
        print("Flujo: trend_finder.py -> run_pipeline.py (paquetes) -> revisión humana -> uploader.py (privado por defecto)")
        print("Asignación de slots por DINERO (MANDATO 1c): la mezcla semanal se re-pesa a los 2 subtemas de mayor ingreso estimado por pieza (tools/revenue_estimator.py --ranking); excepción embudo para el subtema que trae los subs.")
    if args.emit_cron:
        print("# Sugerido (revisar y pegar con `crontab -e`); prepara paquetes a las 06:30, nunca publica solo:")
        print(f"30 6 * * * cd {ROOT} && python3 tools/trend_finder.py --max {n} >> output/cron.log 2>&1")
        print(f"35 6 * * * cd {ROOT} && python3 tools/run_pipeline.py --count {n} --render >> output/cron.log 2>&1")
    if args.run_today:
        for cmd in ([sys.executable, "tools/trend_finder.py", "--max", str(n)],
                    [sys.executable, "tools/run_pipeline.py", "--count", str(n)] + (["--dry-run"] if args.dry_run else ["--render"])):
            print("+", " ".join(cmd))
            subprocess.run(cmd, cwd=str(ROOT))

if __name__ == "__main__":
    main()
