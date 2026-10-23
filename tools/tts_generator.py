#!/usr/bin/env python3
"""
tts_generator.py — Voz en español para el video a partir del texto del guión.

RITMO DEL CANAL: 1.20× para TODO el canal (config.yaml tts.rate_factor,
decisión del dueño 2026-10-19/20). Con Piper se aplica --length-scale con el
valor CALIBRADO de config (tts.piper_length_scale = 0.766; el nominal
1/1.20 = 0.833 se queda corto porque Piper no escala lineal: medido
2026-10-20, 0.833 → ×1.108 real y 0.766 → ×1.20 real). Con edge-tts,
rate «+20%». El manifiesto registra rate_factor y length_scale: el QC
(automation/qc.py) verifica que la duración del audio sea consistente con
el ritmo 1.20× EFECTIVO.

Orden de proveedores (el primero disponible gana):
  1) Piper TTS (LOCAL, sin red): modelo neuronal en assets/voices/ definido en
     config.yaml (tts.piper_model). Instalación: pip install piper-tts y el
     modelo .onnx + .onnx.json en assets/voices/. Es el proveedor por defecto
     del canal desde el pivote a finanzas (2026-10-20): voz real verificada.
  2) edge-tts (red): voz es-MX-JorgeNeural. En esta máquina el tráfico sale por
     el proxy de egreso: se pasa HTTPS_PROXY y se parchea el contexto SSL de
     edge_tts para que incluya el CA del sistema (SSL_CERT_FILE), porque
     edge-tts usa certifi por defecto y el proxy presenta su propio CA.
  3) pyttsx3 + motor del sistema.
  4) espeak-ng / espeak por subprocess.
  5) Fallback documentado: WAV silencioso de la duración estimada + manifiesto
     tts_manifest.json explicando qué falta. El pipeline NO se rompe.

Uso:
    python3 tools/tts_generator.py --text-file content/scripts/<slug>.txt --out output/<slug>/voice.mp3
    python3 tools/tts_generator.py --text "Hola, esto es una prueba" --out /tmp/prueba.mp3
Nota: con Piper/pyttsx3/espeak el audio real queda en <out>.wav y el manifiesto
apunta a ese archivo; run_pipeline.py y video_assembler.py lo detectan solos.
"""
import argparse, asyncio, json, os, shutil, subprocess, sys, wave
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, load_config, estimate_seconds

def silent_wav(path: Path, seconds: float):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path.with_suffix(".wav")), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100)
        w.writeframes(b"\x00\x00" * int(44100 * max(1.0, seconds)))
    return path.with_suffix(".wav")

def try_piper(text: str, out: Path, cfg: dict, manifest: dict) -> bool:
    tts_cfg = cfg.get("tts", {}) if isinstance(cfg, dict) else {}
    model_rel = tts_cfg.get("piper_model", "assets/voices/es_MX-claude-high.onnx")
    model = ROOT / model_rel
    if not model.exists():
        manifest["piper_error"] = f"modelo no encontrado: {model}"
        return False
    try:
        import piper  # noqa: F401  (verifica que el paquete está en este intérprete)
    except ImportError:
        manifest["piper_error"] = "paquete piper-tts no instalado en este intérprete (usa .venv/bin/python)"
        return False
    # Ritmo del canal: 1.20× (orden del dueño 2026-10-19/20 — «voz un poco más
    # rápida y natural»). En Piper, length_scale < 1 acelera, pero NO lineal:
    # el nominal 1/1.20 = 0.833 dio ×1.108 real; el valor de config (0.766)
    # está CALIBRADO para el ×1.20 efectivo con esta voz (ver config.yaml).
    try:
        factor = float(tts_cfg.get("rate_factor", 1.20) or 1.20)
    except Exception:
        factor = 1.20
    length_scale = tts_cfg.get("piper_length_scale") or round(1.0 / factor, 3)
    wav_out = out.with_suffix(".wav")
    try:
        proc = subprocess.run([sys.executable, "-m", "piper", "-m", str(model),
                               "-f", str(wav_out),
                               "--length-scale", str(length_scale)],
                              input=text, capture_output=True,
                              text=True, timeout=600)
        if proc.returncode == 0 and wav_out.exists() and wav_out.stat().st_size > 10000:
            manifest.update({"provider": "piper", "piper_model": model_rel, "out": str(wav_out),
                             "rate_factor": factor, "length_scale": float(length_scale)})
            return True
        manifest["piper_error"] = (proc.stderr or "")[-400:]
    except Exception as e:
        manifest["piper_error"] = str(e)
    return False

def try_edge_tts(text: str, out: Path, voice: str, rate: str, manifest: dict) -> bool:
    try:
        import edge_tts
        # Parche SSL: edge_tts usa certifi; el proxy de egreso de esta máquina
        # presenta el CA de SSL_CERT_FILE. Combinamos ambos paquetes.
        try:
            import ssl, certifi, edge_tts.communicate as _ec
            ctx = ssl.create_default_context(cafile=certifi.where())
            ca_env = os.environ.get("SSL_CERT_FILE")
            if ca_env and Path(ca_env).exists():
                ctx.load_verify_locations(cafile=ca_env)
            _ec._SSL_CTX = ctx
        except Exception as e:
            manifest["edge_tts_ssl_patch"] = str(e)
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        async def run():
            await edge_tts.Communicate(text, voice, rate=rate, proxy=proxy).save(str(out))
        asyncio.run(run())
        if out.exists() and out.stat().st_size > 5000:
            manifest.update({"provider": "edge-tts", "voice": voice, "out": str(out)})
            return True
        manifest["edge_tts_error"] = "salida vacía o demasiado pequeña"
    except ImportError:
        manifest["edge_tts_error"] = "edge-tts no instalado"
    except Exception as e:
        manifest["edge_tts_error"] = str(e)[:400]
    return False

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text"); ap.add_argument("--text-file")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    text = args.text or Path(args.text_file).read_text(encoding="utf-8").strip()
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    cfg = load_config(); tts_cfg = cfg.get("tts", {}) if isinstance(cfg, dict) else {}
    voice = tts_cfg.get("voice", "es-MX-JorgeNeural"); rate = tts_cfg.get("rate", "+20%")
    manifest = {"provider": None, "voice": voice, "chars": len(text), "out": str(out)}
    # 1) Piper local
    if not manifest["provider"] and try_piper(text, out, cfg, manifest):
        pass
    # 2) edge-tts
    if not manifest["provider"]:
        try_edge_tts(text, out, voice, rate, manifest)
    # 3) pyttsx3
    if not manifest["provider"]:
        try:
            import pyttsx3
            eng = pyttsx3.init(); eng.save_to_file(text, str(out)); eng.runAndWait()
            manifest["provider"] = "pyttsx3"
        except Exception as e:
            manifest["pyttsx3_error"] = str(e)
    # 4) espeak
    if not manifest["provider"]:
        exe = shutil.which("espeak-ng") or shutil.which("espeak")
        if exe:
            try:
                subprocess.run([exe, "-v", "es", "-w", str(out.with_suffix(".wav")), text], check=True)
                manifest["provider"] = exe; manifest["out"] = str(out.with_suffix(".wav"))
            except Exception as e:
                manifest["espeak_error"] = str(e)
    # 5) fallback silencioso documentado
    if not manifest["provider"]:
        wav = silent_wav(out, estimate_seconds(len(text.split())))
        manifest.update({"provider": "fallback-silencio", "out": str(wav),
                         "pending": "Instala la voz real: pip install piper-tts + modelo en assets/voices/ (ver requirements.txt)"})
    (out.parent / "tts_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
