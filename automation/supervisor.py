#!/usr/bin/env python3
"""
supervisor.py — Chequeo de salud del negocio pasivo (ver AUTONOMIA.md).

Verifica y registra en automation/logs/supervisor.log + automation/state.json:
  - Disco libre >= automation.disk_limit_gb (si no, BLOQUEA producción).
  - Dependencias: ffmpeg/ffprobe, Piper (modelo+paquete en .venv) o edge-tts, PIL/yaml.
  - Cola de temas: pending >= piezas principales/día (shorts_per_day=1) x 7 días.
  - Mezcla editorial (§1d): reparte la cola pendiente por categoría de alto
    valor (40/30/20/10) y alerta si una categoría queda en cero o dinero
    acapara la cola (checks.editorial_mix; no bloquea).
    CADENCIA NUEVA 2026-10-20: 1 pieza principal muy trabajada al día
    (metraje_real) + Shorts espejo derivados de los largos; el «3 al día»
    quedó retirado por el dueño («todo más trabajado»).
  - MODO ESPEJO: inbox-largos/ sin procesar (registro durable en
    automation/mirror_registry.json; el resumen queda también en state.json).
    Cada largo nuestro se procesa UNA sola vez (huella nombre+size+mtime).
  - Últimos renders: los 3 paquetes más recientes de output/ válidos por ffprobe.
  - OAuth: client_secrets.json / token.json presentes o ausentes (sin inventar nada).
  - Fallos consecutivos en state (2 seguidos -> pausa automática de publicación).
Si algo falla, deja el motivo en state.json (publish_blocked / reasons) y el
sistema NO publica basura: daily_run.sh consulta este estado.

Uso: python3 automation/supervisor.py   (exit 0 sano/degradado, 2 bloqueado)
"""
import json, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from common import load_json, save_json, load_config, mix_category, mix_pcts  # noqa: E402

AUTO = ROOT / "automation"
STATE = AUTO / "state.json"
LOG = AUTO / "logs" / "supervisor.log"

def log(msg: str):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f: f.write(line + "\n")

def ffprobe_ok(mp4: Path) -> bool:
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(mp4)], capture_output=True, text=True)
        return float(p.stdout.strip()) > 5
    except Exception:
        return False

def main():
    if "--touch-supervision" in sys.argv:
        # Muse registra su revisión (lote semanal, barato en tokens: solo
        # resúmenes/CSV/reportes, nunca video crudo). Ver AUTONOMIA.md.
        prev = load_json(STATE, {})
        prev["last_supervision_at"] = datetime.now(timezone.utc).isoformat()
        prev["conservative_mode"] = False
        save_json(STATE, prev)
        log("supervisión de Muse registrada (touch) — modo conservador apagado")
        print(json.dumps({"last_supervision_at": prev["last_supervision_at"]}, indent=2))
        return
    cfg = load_config()
    acfg = cfg.get("automation", {}) if isinstance(cfg, dict) else {}
    cad = cfg.get("cadence", {}) if isinstance(cfg, dict) else {}
    spd = int(acfg.get("shorts_per_day") or cad.get("shorts_per_day") or 1)
    min_free = float(acfg.get("disk_limit_gb") or 5)
    prev = load_json(STATE, {})
    checks, reasons, blocked = {}, [], False

    free_gb = round(shutil.disk_usage(ROOT).free / 1e9, 1)
    checks["disk_free_gb"] = free_gb
    if free_gb < min_free:
        blocked = True; reasons.append(f"disco libre {free_gb} GB < mínimo {min_free} GB")

    deps = {"ffmpeg": bool(shutil.which("ffmpeg")), "ffprobe": bool(shutil.which("ffprobe"))}
    venv_py = ROOT / ".venv" / "bin" / "python"
    py = str(venv_py) if venv_py.exists() else sys.executable
    probe = subprocess.run([py, "-c", "import piper, yaml, PIL; print('ok')"],
                           capture_output=True, text=True)
    deps["piper_en_venv"] = probe.returncode == 0
    probe2 = subprocess.run([py, "-c", "import edge_tts; print('ok')"], capture_output=True, text=True)
    deps["edge_tts_en_venv"] = probe2.returncode == 0
    model = ROOT / ((cfg.get("tts", {}) or {}).get("piper_model", "assets/voices/es_MX-claude-high.onnx"))
    deps["piper_modelo"] = model.exists()
    checks["deps"] = deps
    if not (deps["ffmpeg"] and deps["ffprobe"]):
        blocked = True; reasons.append("falta ffmpeg/ffprobe")
    if not (deps["piper_en_venv"] and deps["piper_modelo"]) and not deps["edge_tts_en_venv"]:
        blocked = True; reasons.append("sin motor de voz disponible (ni Piper ni edge-tts)")

    queue = load_json(ROOT / "content" / "queue.json", [])
    pending = [q for q in queue if q.get("status") == "pending"]
    need = spd * 7
    checks["queue_pending"] = len(pending); checks["queue_needed_7d"] = need
    if len(pending) < need:
        reasons.append(f"cola de temas baja: {len(pending)} pending < {need} (7 días) — trend_finder en la próxima corrida diaria")

    # --- Mezcla editorial (MANDATO §1d): la cola pendiente debe repartirse
    # 40/30/20/10 por categoría de alto valor; alerta (sin bloquear) si una
    # categoría con cuota >=10% no tiene temas o si dinero lo acapara todo.
    pcts = mix_pcts(cfg if isinstance(cfg, dict) else None)
    mix_counts = {c: 0 for c in pcts}
    for q in pending:
        cat = mix_category(q.get("kind"), q.get("categoria_mezcla") or q.get("categoria"))
        if cat in mix_counts:
            mix_counts[cat] += 1
    n_pend = max(1, len(pending))
    mix_shares = {c: round(100.0 * n / n_pend, 1) for c, n in mix_counts.items()}
    checks["editorial_mix"] = {"objetivo_pct": pcts, "pending_por_categoria": mix_counts,
                               "pending_share_pct": mix_shares}
    if len(pending) >= need:
        for cat, pct in pcts.items():
            if pct >= 10 and mix_counts.get(cat, 0) == 0:
                reasons.append(f"mezcla editorial (§1d): categoría «{cat}» (objetivo {pct:.0f}%) SIN temas en cola "
                               "— ampliar el pool de esa categoría (content/temas-mixtos.json)")
        if mix_shares.get("dinero-finanzas", 0) > 60:
            reasons.append(f"mezcla editorial (§1d): dinero-finanzas acapara el {mix_shares['dinero-finanzas']}% "
                           f"de la cola pendiente (objetivo 40%) — la rotación por déficit debe corregirlo")

    pkgs = sorted((ROOT / "output").glob("*/short.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
    renders = {p.parent.name: ffprobe_ok(p) for p in pkgs}
    checks["last_renders_ffprobe"] = renders
    if pkgs and not any(renders.values()):
        blocked = True; reasons.append("ningún render reciente válido por ffprobe")

    qdir = ROOT / "output" / "_cuarentena"
    n_q = len(list(qdir.glob("*/short.mp4"))) if qdir.exists() else 0
    q_max = int(acfg.get("quarantine_max_mp4") or 10)
    checks["quarantine_mp4"] = n_q; checks["quarantine_max"] = q_max
    if n_q > q_max:
        reasons.append(f"ALERTA cuarentena: {n_q} MP4 sin resolver > tope {q_max} (subidas fallidas acumuladas)")

    # --- Modo espejo: largos cargados -> Shorts (una sola vez por archivo) ---
    mcfg = cfg.get("mirror_sources", {}) if isinstance(cfg, dict) else {}
    inbox = ROOT / (mcfg.get("inbox_dir") or "inbox-largos")
    registry = load_json(AUTO / "mirror_registry.json", [])
    seen_fp = {r.get("fingerprint") for r in registry if isinstance(r, dict)}
    def _fp(p: Path) -> str:
        st = p.stat(); return f"{p.name}:{st.st_size}:{int(st.st_mtime)}"
    inbox_files = [p for p in sorted(inbox.glob("*")) if p.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm")] if inbox.exists() else []
    pending_mirror = [p.name for p in inbox_files if _fp(p) not in seen_fp]
    clips_total = len(list((ROOT / "output" / "clips").glob("*/short.mp4"))) if (ROOT / "output" / "clips").exists() else 0
    checks["mirror"] = {"inbox_dir": str(inbox), "inbox_pending": len(pending_mirror),
                        "pending_files": pending_mirror, "processed_total": len(registry),
                        "clips_producidos": clips_total,
                        "platforms": cfg.get("platforms", {}) if isinstance(cfg, dict) else {}}
    if pending_mirror:
        reasons.append(f"modo espejo: {len(pending_mirror)} video(s) largo(s) sin procesar en {inbox.name}/ "
                       "— daily_run los convierte en Shorts (YouTube + TikTok)")

    oauth = {"client_secrets": (ROOT / "client_secrets.json").exists(),
             "token": (ROOT / "token.json").exists()}
    checks["oauth"] = oauth
    if not oauth["token"]:
        reasons.append("sin token OAuth: no se puede publicar (esperado hasta que el dueño cree el canal)")

    # --- Semáforo de ausencia de Muse (anti-bloqueo por tokens) ---
    last_sup = prev.get("last_supervision_at") or datetime.now(timezone.utc).isoformat()
    try:
        age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(last_sup)).total_seconds() / 3600
    except Exception:
        age_h = 0.0
    conservative = age_h > 72
    checks["supervision_age_hours"] = round(age_h, 1)
    if conservative:
        reasons.append(f"modo CONSERVADOR activo: sin supervisión de Muse hace {age_h:.0f} h (>72 h) — "
                       "solo cola validada/evergreen, sin estrenos ni experimentos")

    failures = int(prev.get("consecutive_failures", 0))
    max_fail = int(acfg.get("max_consecutive_failures") or 2)
    paused = failures >= max_fail
    if paused:
        reasons.append(f"pausa automática: {failures} fallos consecutivos >= {max_fail}")
    auto_publish = bool(acfg.get("auto_publish"))
    publish_blocked = blocked or paused or not oauth["token"] or not auto_publish

    # --- Monetización (datos estructurados para dashboard; honesto: hoy $0) ---
    import csv as _csv
    from datetime import date as _date, timedelta as _td
    _rows = []
    _acsv = ROOT / "content" / "analytics.csv"
    if _acsv.exists():
        _rows = list(_csv.DictReader(_acsv.open(encoding="utf-8")))
    _last = _rows[-1] if _rows else {}
    _subs = float(_last.get("subs") or 0); _views = float(_last.get("shorts_views_90d") or 0)
    _hours = float(_last.get("watch_hours_12m") or 0); _rev = float(_last.get("revenue_usd") or 0)
    _proj = None
    if len(_rows) >= 2 and _subs > 0:
        try:
            _d0 = _date.fromisoformat(_rows[0]["date"]); _d1 = _date.fromisoformat(_last["date"])
            _rate = (_subs - float(_rows[0].get("subs") or 0)) / max(1, (_d1 - _d0).days)
            if _rate > 0 and _subs < 1000:
                _proj = str(_d1 + _td(days=int((1000 - _subs) / _rate)))
        except Exception:
            pass
    monetization = {
        "revenue_real_usd": _rev, "revenue_note": "antes del Partner Program YouTube no paga anuncios",
        "first_payout_target_usd": 100,
        "subs": _subs, "subs_target": 1000,
        "shorts_views_90d": _views, "shorts_views_target": 10000000,
        "watch_hours_12m": _hours, "watch_hours_target": 4000,
        "pace_pieces_per_day": spd, "pace_pieces_90d": spd * 90,
        "shorts_route_avg_views_per_piece": round(10000000 / max(1, spd * 90)),
        "hours_route_long_views_needed_at_5min": 48000,
        "projected_date_1000_subs": _proj,
        "projected_note": _proj or "sin datos aún (canal sin publicar)",
    }
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        import revenue_estimator as _re
        monetization["revenue_estimate_mensual"] = _re.monthly_estimate(spd, 1)
        monetization["subtema_ranking_por_dinero"] = _re.ranking()
        monetization["pivote_por_dinero"] = {
            "top2": [r["subtema"] for r in _re.ranking()[:2]],
            "regla": "la mezcla semanal se re-pesa a los 2 subtemas de mayor ingreso estimado por pieza; "
                     "excepción embudo: el subtema que trae los subs no pierde su slot (MANDATO 1c)"}
    except Exception as _e:
        monetization["revenue_estimate_error"] = str(_e)
    checks["monetization"] = monetization

    state = {"updated_at": datetime.now(timezone.utc).isoformat(),
             "monetization": monetization,
             "last_supervision_at": last_sup, "conservative_mode": conservative,
             "healthy": not blocked, "publish_blocked": publish_blocked,
             "publication_paused": paused, "consecutive_failures": failures,
             "auto_publish_config": auto_publish, "checks": checks, "reasons": reasons,
             "python": py}
    save_json(STATE, state)
    log(f"supervisor: healthy={state['healthy']} publish_blocked={publish_blocked} reasons={reasons}")
    print(json.dumps(state, ensure_ascii=False, indent=2))
    sys.exit(2 if blocked else 0)

if __name__ == "__main__":
    main()
