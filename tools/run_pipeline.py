#!/usr/bin/env python3
"""
run_pipeline.py / scheduler.py — Orquesta TODO el flujo, de tendencia a paquete.

Flujo por tema:
  tendencia (queue.json o --topic) -> guión -> voz (TTS) -> portada+metadatos
  -> video (ffmpeg) -> validación de paquete (uploader --dry-run)
  -> paquete listo en output/<slug>/ con package_manifest.json

La subida real es un paso APARTE y manual (uploader.py) con el OAuth del dueño;
este orquestador NUNCA publica solo. Respeta config.yaml: default_privacy=private.

Uso:
    python3 tools/run_pipeline.py --dry-run --topic "Tema de ejemplo"
    python3 tools/run_pipeline.py --count 3            # 3 temas de la cola
    python3 tools/run_pipeline.py --count 1 --render   # incluye render ffmpeg real
Registro: output/pipeline.log (append) + manifest por paquete.
"""
import argparse, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, CONTENT, OUTPUT, load_json, save_json, slugify
import script_generator, title_thumbnail

TOOLS = Path(__file__).parent

def log(msg: str):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with (OUTPUT / "pipeline.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")

def run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")

def process(topic: str, kind: str, angle: str, dry_run: bool, render: bool) -> dict:
    slug = slugify(topic)
    pkg = OUTPUT / slug; pkg.mkdir(parents=True, exist_ok=True)
    log(f"[{slug}] tema: {topic}")
    # 1) Guión
    script = script_generator.generate(topic, kind, angle)
    script_file = CONTENT / "scripts" / f"{slug}.json"
    script_file.parent.mkdir(parents=True, exist_ok=True)
    save_json(script_file, script)
    (CONTENT / "scripts" / f"{slug}.txt").write_text(script["full_text"], encoding="utf-8")
    log(f"[{slug}] guión ok: {script['word_count']} palabras, ~{script['estimated_seconds']} s, modo={script['mode']}")
    # 2) Metadatos + portada (la descripción lleva el bloque «Fuentes:» con
    #    nombre, fecha y URL real cuando el tema es de actualidad)
    meta = title_thumbnail.build_package(topic, pkg, script["sections"].get("hook_0_3s", ""),
                                         news=script.get("news"))
    if script.get("news"):
        save_json(pkg / "metadata.json", meta)
    log(f"[{slug}] título ({meta['title_chars']} car): {meta['title']} | portada: {meta['cover']}")
    # 3) Voz
    voice_out = pkg / "voice.mp3"
    if dry_run:
        log(f"[{slug}] TTS en dry-run: se valida la llamada sin generar audio")
        tts_info = {"dry_run": True, "would_generate": str(voice_out)}
    else:
        rc, out_txt = run([sys.executable, str(TOOLS / "tts_generator.py"),
                           "--text", script["full_text"], "--out", str(voice_out)])
        try:
            tts_info = json.loads(out_txt[out_txt.index("{"):])
        except Exception:
            tts_info = {"rc": rc, "raw_tail": out_txt[-400:]}
        log(f"[{slug}] TTS: {tts_info.get('provider', 'ver manifiesto')}")
    # 4) Video
    _wav = pkg / "voice.wav"
    audio_arg = str(voice_out) if voice_out.exists() else (str(_wav) if _wav.exists() else "")
    video_info = {}
    if render and not dry_run:
        # Assembler según el formato que declara el guión (estándar vigente:
        # metraje_real; legado con imagen: foto_real; resto: estándar).
        fmt = (script.get("format") or "").strip()
        if fmt == "metraje_real":
            asm_cmd = [sys.executable, str(TOOLS / "footage_assembler.py"),
                       "--script-json", str(script_file), "--audio", audio_arg,
                       "--out", str(pkg / "short.mp4")]
        elif fmt in ("foto_real", "imagen_generada"):
            asm_cmd = [sys.executable, str(TOOLS / "animated_assembler.py"),
                       "--script-json", str(script_file), "--audio", audio_arg,
                       "--out", str(pkg / "short.mp4")]
        else:
            asm_cmd = [sys.executable, str(TOOLS / "video_assembler.py"),
                       "--script-json", str(script_file), "--audio", audio_arg,
                       "--cover", meta["cover"], "--out", str(pkg / "short.mp4")]
        rc, out_txt = run(asm_cmd)
        video_info = {"rc": rc, "tail": out_txt[-500:], "assembler": asm_cmd[1].split("/")[-1]}
        log(f"[{slug}] render ffmpeg rc={rc} ({video_info['assembler']})")
    else:
        rc, out_txt = run([sys.executable, str(TOOLS / "video_assembler.py"),
                           "--script-json", str(script_file), "--cover", meta["cover"],
                           "--out", str(pkg / "short.mp4"), "--dry-run"])
        try:
            video_info = json.loads(out_txt[out_txt.index("{"):])
        except Exception:
            video_info = {"rc": rc, "raw_tail": out_txt[-400:]}
        log(f"[{slug}] video dry-run ok (ffmpeg: {video_info.get('ffmpeg')}, srt: {video_info.get('srt')})")
    # 5) Validación de paquete
    rc, out_txt = run([sys.executable, str(TOOLS / "uploader.py"), "--package", str(pkg), "--dry-run"])
    try:
        validation = json.loads(out_txt[out_txt.index("{"):])
    except Exception:
        validation = {"rc": rc, "raw_tail": out_txt[-400:]}
    manifest = {"slug": slug, "topic": topic, "created_at": datetime.now(timezone.utc).isoformat(),
                "dry_run": dry_run, "render_requested": render, "script": str(script_file),
                "metadata": meta, "tts": tts_info, "video": video_info, "validation": validation,
                "next_step_human": "Revisar short.mp4 y subir con: python3 tools/uploader.py --package "
                                   f"output/{slug}  (privado por defecto; --privacy public solo con OK del dueño)"}
    save_json(pkg / "package_manifest.json", manifest)
    log(f"[{slug}] paquete listo en {pkg} — validación: {validation.get('checks', {})}")
    return manifest

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic"); ap.add_argument("--kind", default="evergreen"); ap.add_argument("--angle", default="")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--render", action="store_true", help="Render real con ffmpeg (si no, solo dry-run de video)")
    args = ap.parse_args()
    topics = []
    if args.topic:
        topics = [{"topic": args.topic, "kind": args.kind, "angle": args.angle}]
    else:
        q = load_json(CONTENT / "queue.json", [])
        topics = [x for x in q if x.get("status") == "pending"][: args.count]
        if not topics:
            print("Cola vacía: corre primero tools/trend_finder.py"); sys.exit(1)
    results = [process(t["topic"], t.get("kind", "evergreen"), t.get("angle", ""), args.dry_run, args.render)
               for t in topics]
    # Marcar procesados en la cola
    if not args.topic:
        q = load_json(CONTENT / "queue.json", [])
        done = {r["slug"] for r in results}
        for item in q:
            if item.get("slug") in done:
                item["status"] = "packaged"
        save_json(CONTENT / "queue.json", q)
    print(json.dumps({"packages": [r["slug"] for r in results]}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
