#!/usr/bin/env python3
"""
frames.py — QC visual por capturas (corrección 2026-10-20).

La falla original fue NO mirar los videos. Ahora ningún paquete llega a
ready/ sin capturas: 3 cuadros (segundo 2, mitad, penúltimo segundo) en
<paquete>/frames/ + una hoja de contacto (montaje de los 3) en
<paquete>/frames/contacto.png para inspección humana/de Muse.
automation/qc.py verifica que existan.
"""
import json, subprocess, sys
from pathlib import Path

def probe_duration(path) -> float:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try: return float(p.stdout.strip())
    except Exception: return 0.0

def extract_frames(mp4: Path, pkg_dir: Path) -> dict:
    from PIL import Image
    dur = probe_duration(mp4)
    if dur <= 0:
        return {"frames_generated": False, "error": "sin duración (ffprobe)"}
    fdir = Path(pkg_dir) / "frames"; fdir.mkdir(parents=True, exist_ok=True)
    times = {"frame-2s.png": min(2.0, dur / 3), "frame-mitad.png": dur / 2,
             "frame-penultimo.png": max(0.5, dur - 2.0)}
    made = []
    for name, t in times.items():
        out = fdir / name
        r = subprocess.run(["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(mp4),
                            "-frames:v", "1", str(out)], capture_output=True, text=True)
        if r.returncode == 0 and out.exists(): made.append(str(out))
    sheet = None
    if len(made) == 3:
        imgs = [Image.open(p).resize((540, 960)) for p in made]
        sheet_img = Image.new("RGB", (540 * 3, 960), "#000000")
        for i, im in enumerate(imgs): sheet_img.paste(im, (540 * i, 0))
        sheet = fdir / "contacto.png"; sheet_img.save(sheet)
    return {"frames_generated": len(made) == 3 and sheet is not None,
            "frames": made, "contact_sheet": str(sheet) if sheet else None,
            "duration_sec": round(dur, 2)}

if __name__ == "__main__":
    print(json.dumps(extract_frames(Path(sys.argv[1]), Path(sys.argv[2])), ensure_ascii=False, indent=2))
