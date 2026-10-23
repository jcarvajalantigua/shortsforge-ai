#!/usr/bin/env python3
"""Ciclo escritor-juez para guiones de Shorts (orden del dueño 2026-10-22:
"que llegue a un 80 es mejor" + "jev como juez").

- ESCRITOR: Hermes / bonsai-27b-q1 (gateway 127.0.0.1:8080, estilo OpenAI).
- JUEZ 1 (reglas): retention_optimizer.score_script — puntaje exacto + motivos.
- JUEZ 2 (jev): POST /v1/decide de Hermes (jev-auto, bracket-scoring) decide
  publicar / reescribir / descartar sobre el texto y los motivos del Juez 1.
- El escritor reescribe con AMBAS retroalimentaciones. Meta: 80. Intentos: 3.
  Se conserva el mejor; si el mejor queda <70, devuelve None (respaldo).
"""
import json, os, re, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import script_generator as sg
from retention_optimizer import score_script

GW = os.environ.get("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
TARGET = 100  # meta del dueño 2026-10-22: iterar hasta acercarse a 100
FLOOR = 70
MAX_ATTEMPTS = 4

BASE_PROMPT = (
    "Escribe SOLO el texto corrido de un guion de YouTube Short en español puro, "
    "105 a 135 palabras exactas, para hispanos en USA, sobre el tema: «{t}». "
    "REGLAS DURAS: nada de título, nada de markdown, nada de marcas de tiempo, nada de emojis: "
    "únicamente las frases que dice la voz. ESTRUCTURA OBLIGATORIA en 5 segmentos cortos "
    "separados por saltos de línea: (1) gancho-pregunta con cifra concreta que funcione SIN contexto; "
    "(2) dato o ejemplo numérico sencillo; (3) explicación simple de cualquier término técnico; "
    "(4) el error común o el giro que nadie espera; (5) cierre que RESPUESTA la pregunta del gancho "
    "con la palabra «respuesta» y devuelve la pregunta al espectador invitándolo a guardar el video. "
    "Educación general: sin consejo financiero personalizado ni promesas de rendimiento."
)


def _opener():
    return sg._hermes_opener(GW)


def _post(path, payload, timeout=180):
    cfg = sg.load_config()
    hdrs = {"Content-Type": "application/json",
            "Authorization": "Bearer " + sg._hermes_key(cfg)}
    req = urllib.request.Request(GW + path, data=json.dumps(payload).encode(), headers=hdrs)
    with _opener().open(req, timeout=timeout) as r:
        return json.loads(r.read())


def _to_script(topic, kind, text):
    text = text.strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    if len(paras) < 3:
        paras = [p.strip() for p in re.split(r"(?<=[.?!])\s+", text) if p.strip()]
    hook = paras[0] if paras else text[:120]
    closing = paras[-1] if paras else ""
    senal = sg.derive_senal(closing, text) or sg.SENAL_POR_KIND.get(kind, "suscripcion")
    words = len(text.split())
    return {"topic": topic, "kind": kind, "mode": "llm-hermes-jev",
            "full_text": text, "senal_objetivo": senal,
            "estructura_alcance": {"hook_sin_contexto": True, "micro_curiosidad_cada_s": "12-15",
                                   "cierre_loop": "¿" in closing or "?" in closing,
                                   "senal_objetivo": senal},
            "sections": {"hook_0_3s": hook, "desarrollo": paras[1:-1], "cierre_cta": closing},
            "word_count": words, "estimated_seconds": sg.estimate_seconds(words),
            "on_screen_text": [], "visual_plan": [], "disclaimer": sg.DISCLAIMER}


def jev_judge(script, motivos):
    q = ("¿Este guion de YouTube Short para hispanos en USA retiene a la audiencia hasta el final "
         "y merece producirse tal cual? Los motivos del medidor automático son: " + "; ".join(motivos))
    try:
        out = _post("/decide", {"question": q, "context": "GUION:\n" + script["full_text"],
                                "options": ["publicar", "reescribir", "descartar"]}, timeout=120)
        return out.get("decision", ""), (out.get("raw", "") or "")[-400:]
    except Exception as e:
        return "", f"(jev no respondió: {e})"


def _winner_guidance():
    """Patrones de retención ALTA verificados (tools/self_improve.py los escribe
    solo cuando un video real supera la puerta de retención). Sin ganadores
    verificados, no se inyecta nada: el sistema no aprende de ruido."""
    try:
        txt = open("content/retention-winners.md").read()
        ini = txt.index("## Patrones verificados")
        bloque = txt[ini:][:900]
        if "ninguno" in bloque.lower() and "pendiente" in bloque.lower():
            return ""
        return "\n\nPATRONES GANADORES VERIFICADOS (videos reales con retención muy alta — imita su estructura):\n" + bloque
    except Exception:
        return ""


def generate_judged(topic, kind="evergreen", log=print):
    prompt = BASE_PROMPT.format(t=topic) + _winner_guidance()
    best, best_score = None, -1
    feedback = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        t0 = time.time()
        try:
            out = _post("/chat/completions",
                        {"model": "bonsai-27b-q1",
                         "messages": [{"role": "user", "content": prompt + feedback}],
                         "temperature": 0.6})
            text = out["choices"][0]["message"]["content"]
        except Exception as e:
            log(f"[juez] intento {attempt}: Hermes falló ({e})")
            continue
        cand = _to_script(topic, kind, text)
        sc = score_script(cand)
        score, motivos = sc["score"], sc["motivos"]
        log(f"[juez] intento {attempt}: score {score} en {time.time()-t0:.0f}s "
            f"({cand['word_count']} palabras)")
        if score > best_score:
            best, best_score = cand, score
        if score >= TARGET:
            return best, best_score, attempt
        decision, raw = jev_judge(cand, motivos)
        log(f"[juez] jev: {decision}")
        feedback = ("\n\nTU INTENTO ANTERIOR SACÓ " + str(score) + "/100. Problemas medidos: "
                    + "; ".join(m for m in motivos if "+" not in m)
                    + (f". El juez editorial decidió: {decision}." if decision else "")
                    + " Reescribe corrigiendo TODO eso, misma estructura de 5 segmentos, "
                      "105 a 135 palabras exactas.")
    return (best, best_score, MAX_ATTEMPTS) if best_score >= FLOOR else (None, best_score, MAX_ATTEMPTS)


if __name__ == "__main__":
    topics = sys.argv[1:] or ["El error de crédito que baja tu puntaje sin que lo sepas"]
    for t in topics:
        print("TEMA:", t)
        s, score, n = generate_judged(t)
        print("RESULTADO:", "score", score, "| intentos", n, "| modo", (s or {}).get("mode"))
        if s:
            print("HOOK:", s["sections"]["hook_0_3s"][:100])
        print()
