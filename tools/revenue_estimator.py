#!/usr/bin/env python3
"""
revenue_estimator.py — Estimación de ingresos por tema/formato y pivote por DINERO.

TODO lo que produce esta herramienta es ESTIMADO (nunca ingreso real): sirve
para asignar los slots diarios hacia lo que más dinero deja por pieza, no para
prometer cifras (MANDATO.md: pivote por dinero, con excepción de embudo).

RPM por subtema (USD por 1.000 vistas), desde los rangos investigados en 2026:
finanzas CPM $15-40 / RPM largo $10-22 · IA y tutorías CPM $15-22 ·
Shorts finanzas $0.15-0.25/1.000 · largo finanzas $15-20 de referencia.
  subtema            Shorts (pes/base/opt)     Largo (pes/base/opt)
  llc-impuestos      0.18 / 0.22 / 0.28        15 / 20 / 26   (alto: anunciante caro USA)
  credito            0.16 / 0.21 / 0.27        14 / 19 / 25   (alto)
  ia-negocios        0.15 / 0.20 / 0.26        13 / 18 / 24   (alto: SaaS/herramientas)
  actualidad         0.15 / 0.20 / 0.26        12 / 17 / 23   (noticias dinero USA)
  ahorro-cuentas     0.14 / 0.18 / 0.24        11 / 16 / 22   (medio-alto)
  errores/historias  0.06 / 0.10 / 0.15         5 /  8 / 12   (bajo: motivación genérica)

Vistas esperadas por defecto (canal nuevo, ESTIMADO): Short estándar 3.000
base (1.000 pesimista / 12.000 optimista); animado x1.15 (hipótesis de
RETENCION.md, a validar en 2 semanas); largo 4.000 base (1.500 / 15.000).

Uso:
    python3 tools/revenue_estimator.py --demo
    python3 tools/revenue_estimator.py --subtema llc-impuestos --formato largo --views 8000
    python3 tools/revenue_estimator.py --ranking
"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

RPM = {
    "llc-impuestos":   {"shorts": (0.18, 0.22, 0.28), "largo": (15.0, 20.0, 26.0)},
    "credito":         {"shorts": (0.16, 0.21, 0.27), "largo": (14.0, 19.0, 25.0)},
    "ia-negocios":     {"shorts": (0.15, 0.20, 0.26), "largo": (13.0, 18.0, 24.0)},
    "actualidad":      {"shorts": (0.15, 0.20, 0.26), "largo": (12.0, 17.0, 23.0)},
    "ahorro-cuentas":  {"shorts": (0.14, 0.18, 0.24), "largo": (11.0, 16.0, 22.0)},
    "errores":         {"shorts": (0.06, 0.10, 0.15), "largo": (5.0, 8.0, 12.0)},
    "historias":       {"shorts": (0.06, 0.10, 0.15), "largo": (5.0, 8.0, 12.0)},
    "default":         {"shorts": (0.12, 0.17, 0.22), "largo": (10.0, 15.0, 20.0)},
}
DEFAULT_VIEWS = {"shorts": (1000, 3000, 12000), "largo": (1500, 4000, 15000)}
FORMAT_MULT = {"estandar": 1.0, "animado": 1.15}  # x1.15 = formato premium trabajado (antes «animado»/foto real; desde 2026-10-20 la pieza principal metraje_real)

def _views(formato_tipo: str, escenario: int, views: float | None, formato: str = "estandar") -> float:
    if views is not None:
        return views
    base = DEFAULT_VIEWS[formato_tipo][escenario]
    return base * (FORMAT_MULT.get(formato, 1.0) if formato_tipo == "shorts" else 1.0)

def estimate(subtema: str, formato_tipo: str = "shorts", views: float | None = None,
             formato: str = "estandar") -> dict:
    """Ingreso ESTIMADO de una pieza: vistas x RPM/1000, en 3 escenarios."""
    tabla = RPM.get(subtema, RPM["default"])[formato_tipo]
    escenarios = ["pesimista", "base", "optimista"]
    out = {"subtema": subtema, "tipo": formato_tipo, "formato": formato,
           "etiqueta": "ESTIMADO — no es ingreso real",
           "rpm_usd_por_1000": {"pesimista": tabla[0], "base": tabla[1], "optimista": tabla[2]},
           "ingreso_por_vista_base_usd": round(tabla[1] / 1000, 5)}
    for i, esc in enumerate(escenarios):
        v = _views(formato_tipo, i, views, formato)
        out[esc] = {"vistas_supuestas": int(v), "ingreso_usd": round(v * tabla[i] / 1000, 2)}
    out["ingreso_por_pieza_base_usd"] = out["base"]["ingreso_usd"]
    return out

def ranking() -> list[dict]:
    """Ranking de subtemas por DINERO: ingreso estimado base por pieza
    (Short + largo) y por vista. No por vistas crudas."""
    rows = []
    for sub in RPM:
        if sub == "default": continue
        es = estimate(sub, "shorts"); el = estimate(sub, "largo")
        rows.append({"subtema": sub,
                     "ingreso_por_pieza_shorts_base_usd": es["ingreso_por_pieza_base_usd"],
                     "ingreso_por_pieza_largo_base_usd": el["ingreso_por_pieza_base_usd"],
                     "ingreso_por_vista_base_usd": es["ingreso_por_vista_base_usd"],
                     "rpm_largo_base": RPM[sub]["largo"][1]})
    return sorted(rows, key=lambda r: -r["ingreso_por_pieza_shorts_base_usd"])

def monthly_estimate(pieces_per_day: int = 3, animated_per_day: int = 1) -> dict:
    """Estimación mensual ESTIMADA al ritmo actual con la mezcla vigente
    (actualidad como subtema medio de la mezcla diaria + 4 largos/mes)."""
    days = 30
    std = (pieces_per_day - animated_per_day) * days
    anim = animated_per_day * days
    tot = {"pesimista": 0.0, "base": 0.0, "optimista": 0.0}
    for n, fmt in ((std, "estandar"), (anim, "animado")):
        e = estimate("actualidad", "shorts", formato=fmt)  # ingreso por pieza
        for k in tot: tot[k] += n * e[k]["ingreso_usd"]
    largos = estimate("actualidad", "largo")
    for k in tot: tot[k] = round(tot[k] + 4 * largos[k]["ingreso_usd"], 2)
    return {"etiqueta": "ESTIMADO — no es ingreso real; supone canal monetizado y vistas base de canal nuevo",
            "supuestos": f"{pieces_per_day} pieza(s) principal(es)/día ({animated_per_day} metraje_real) + 1 largo/semana, subtema medio=actualidad",
            **tot}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--ranking", action="store_true")
    ap.add_argument("--subtema", default="actualidad")
    ap.add_argument("--formato", default="shorts", choices=["shorts", "largo"])
    ap.add_argument("--views", type=float)
    ap.add_argument("--animado", action="store_true")
    args = ap.parse_args()
    if args.demo or args.ranking:
        print(json.dumps({"ranking_por_dinero": ranking(),
                          "mensual_al_ritmo_actual": monthly_estimate(),
                          "ejemplo": estimate("llc-impuestos", "largo")}, ensure_ascii=False, indent=2))
        return
    print(json.dumps(estimate(args.subtema, args.formato, args.views,
                              "animado" if args.animado else "estandar"), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
