#!/usr/bin/env python3
"""
video_assembler.py — Short vertical 1080x1920, formato ESTÁNDAR (layout v2).

CORRECCIÓN 2026-10-20 (causa raíz del texto superpuesto): antes la PORTADA
(con el título completo) se usaba como fondo y el filtro `subtitles` de
ffmpeg quemaba los subtítulos en la misma zona central. Ahora todo el texto
lo compone PIL por ZONAS que nunca se tocan (tools/layout.py):
  superior = kicker corto · central = UN dato grande por escena + apoyo ·
  inferior = subtítulos en pastilla (máx 2 líneas). El título completo vive
  SOLO en metadata.json. Sin footage con copyright.

Al terminar genera los cuadros de QC visual (frames/ + hoja de contacto).

Uso:
    python3 tools/video_assembler.py --script-json content/scripts/<slug>.json \
        --audio output/<slug>/voice.wav --out output/<slug>/short.mp4 [--dry-run]
"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import load_json
import layout, render_core

def make_srt(text: str, total_sec: float, out: Path):  # compat: animated/qc antiguos
    return render_core.make_srt(text, total_sec, out)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script-json", required=True)
    ap.add_argument("--audio"); ap.add_argument("--cover", help="(compat) ya NO se usa como fondo")
    ap.add_argument("--out", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    script = load_json(args.script_json, {})
    fails = layout.validate_layout(script)
    result = {"format": "estandar", "layout_version": 2, "layout_failures": fails,
              "out": args.out, "uses_copyrighted_footage": False}
    if fails:
        print(json.dumps(result, ensure_ascii=False, indent=2)); sys.exit(2)
    if args.dry_run:
        result["dry_run"] = True
        print(json.dumps(result, ensure_ascii=False, indent=2)); return
    scenes = layout.effective_scenes(script)
    images = [layout.make_scene_standard(sc, script.get("kicker", "")) for sc in scenes]
    try:
        result.update(render_core.render(script, images, args.audio, Path(args.out)))
    except Exception as e:
        result["error"] = str(e)
        print(json.dumps(result, ensure_ascii=False, indent=2)); sys.exit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
