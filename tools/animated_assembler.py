#!/usr/bin/env python3
"""
animated_assembler.py — Short diario «CON IMAGEN» (1 de los 3), formato v4:
FOTO REAL del tema en alta calidad (orden del dueño 2026-10-20).

Historia: v1 personajes con primitivas PIL, v2 iconografía flat geométrica y
v3 imágenes GENERADAS por IA quedaron TODAS descartadas por el dueño («se ve
horrible la imagen» / «la animación está fea» / «quita esa imagen de fondo;
poner una imagen realista del tema en alta calidad»). El formato vigente es
«foto_real»:

  - Cada escena = UNA FOTOGRAFÍA REAL del tema (alta resolución), a PANTALLA
    COMPLETA con Ken Burns suave (zoom lento; en reuso, espejo + zoom inverso
    para que no se note repetida). Cover-crop 9:16 con foco opcional por foto
    (`crop_centering` en el manifiesto).
  - Solo fuentes con licencia libre o dominio público (Wikimedia Commons,
    Pexels, Unsplash). Fotos y procedencia viven en
    assets/real/<tema>/manifest.json (manifiesto OBLIGATORIO con fuente, URL
    de origen, licencia, autor y dimensiones por foto: sin él, o si falta la
    foto de una escena, este render FALLA con mensaje claro — nunca se cae a
    imágenes generadas ni a iconos en silencio).
  - Zonas de layout.py intactas: kicker en pastilla arriba (0-18%), dato
    grande de la escena en la franja 58-72% sobre pastilla semitransparente,
    subtítulos SOLO en la zona 72-92% (los compone render_core/layout).
  - La escena declara su foto con "image_role" (banco/tarjeta/calendario…)
    o se resuelve por afinidad con su icono (layout.ROLE_AFFINITY).

Al terminar genera los cuadros de QC visual (frames/ + contacto.png).

Uso:
    python3 tools/animated_assembler.py --script-json content/scripts/<slug>.json \
        --audio output/<slug>/voice.wav --out output/<slug>/short.mp4
"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import load_json
import layout, render_core

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script-json", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    script = load_json(args.script_json, {})
    fails = layout.validate_layout(script)
    if fails:
        print(json.dumps({"format": "foto_real", "layout_version": 2, "layout_failures": fails},
                         ensure_ascii=False, indent=2)); sys.exit(2)
    # Puerta dura del formato: sin fotos reales registradas NO hay render.
    rfails = layout.validate_real_images(script)
    if rfails:
        print(json.dumps({"format": "foto_real",
                          "error": "formato «foto real» sin fotos válidas: el render NO cae a imágenes generadas ni a iconos",
                          "real_failures": rfails}, ensure_ascii=False, indent=2))
        sys.exit(3)
    assigns, _ = layout.assign_real_images(script)
    scenes = layout.effective_scenes(script)
    images, scene_meta, used = [], [], []
    prev_path, prev_flip = None, False
    for sc, a in zip(scenes, assigns):
        reuse = prev_path is not None and a["path"] == prev_path
        flip = (not prev_flip) if reuse else False
        kb = "out" if reuse else "in"
        cc = a.get("crop_centering") or (0.5, 0.5)
        images.append(layout.make_scene_real(sc, script.get("kicker", ""), a["path"],
                                             flip=flip, crop_centering=cc))
        scene_meta.append({"kb": kb})
        used.append({"role": a["role"], "file": a["file"], "flip": flip, "ken_burns": kb,
                     "source": a["source"], "source_url": a["source_url"],
                     "license": a["license"], "author": a["author"]})
        prev_path, prev_flip = a["path"], flip
    try:
        result = render_core.render(script, images, args.audio, Path(args.out), scene_meta=scene_meta)
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False, indent=2)); sys.exit(1)
    rdir, rdata = layout.load_real_manifest(script)
    manifest = {"format": "foto_real", "layout_version": 2, "scenes": len(scenes),
                "visual_language": "fotografía real del tema en alta calidad a pantalla completa + Ken Burns suave; sin imágenes generadas por IA, sin iconos ni personajes PIL",
                "real_dir": str(rdir), "real_manifest": str(rdir / "manifest.json"),
                "images": used, "audio": args.audio, **result}
    out = Path(args.out)
    (out.parent / "animated_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
