#!/usr/bin/env python3
"""Auto-mejora SOLO desde retención muy alta (regla del dueño 2026-10-22).

Lee content/analytics.csv (lo alimenta la revisión diaria con datos reales de
YouTube Analytics). Un video se vuelve "maestro" solo si supera la puerta:
vistas >= MIN_VIEWS y porcentaje_visto >= MIN_PCT (o % completado equivalente).
De cada maestro se extrae su patrón (tema, gancho, duración, categoría) y se
agrega a content/retention-winners.md, que el ciclo escritor-juez usa
como guía. Sin maestros nuevos, no escribe nada: no se aprende de ruido.
"""
import csv, os, sys

MIN_VIEWS = 50
MIN_PCT = 60.0
CSV = "content/analytics.csv"
OUT = "content/retention-winners.md"


def _f(v):
    try:
        return float(str(v).replace("%", "").replace(",", "."))
    except Exception:
        return 0.0


def main():
    if not os.path.exists(CSV):
        print("sin analytics.csv — nada que aprender todavía")
        return 0
    rows = list(csv.DictReader(open(CSV)))
    winners = []
    for r in rows:
        views = _f(r.get("vistas") or r.get("views"))
        pct = _f(r.get("pct_visto") or r.get("avg_pct_viewed") or r.get("pct_completado"))
        if views >= MIN_VIEWS and pct >= MIN_PCT:
            winners.append(r)
    prev = open(OUT).read() if os.path.exists(OUT) else ""
    nuevos = []
    for w in winners:
        key = (w.get("video") or w.get("titulo") or "")[:60]
        if key and key not in prev:
            nuevos.append(w)
    if not nuevos:
        print(f"puerta de retención: {len(winners)} maestros, 0 nuevos — sin cambios")
        return 0
    with open(OUT, "a") as f:
        for w in nuevos:
            f.write(f"\n- MAESTRO: «{w.get('titulo') or w.get('video')}» — "
                    f"vistas {w.get('vistas')}, % visto {w.get('pct_visto') or w.get('pct_completado')}, "
                    f"gancho: «{w.get('hook') or ''}», duración {w.get('duracion_s') or ''}s, "
                    f"tema {w.get('tema') or ''}\n")
    print(f"{len(nuevos)} patrón(es) nuevo(s) aprendidos de retención alta")
    return 0


if __name__ == "__main__":
    sys.exit(main())
