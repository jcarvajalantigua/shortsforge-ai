#!/usr/bin/env python3
"""
render_core.py — Motor de render compartido (layout por zonas, corrección 2026-10-20).

Compone cada subtítulo SOBRE la imagen de su escena con PIL (pastilla en la
zona inferior, ver layout.py) y anima cada trozo con un zoompan suave.
Así ningún texto de ffmpeg puede caer fuera de su zona: todo el texto del
video lo dibuja PIL midiendo antes de dibujar.
"""
import json, shutil, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import layout
from frames import extract_frames, probe_duration

def make_srt(text: str, total_sec: float, out: Path):
    """SRT para la subida a YouTube (los subtítulos QUEMADOS en el video los
    compone layout.caption_overlay; este .srt es el archivo del paquete)."""
    words = text.split()
    chunks = [" ".join(words[i:i + 7]) for i in range(0, len(words), 7)] or [text]
    step = total_sec / len(chunks)
    def ts(s):
        h, m = int(s // 3600), int((s % 3600) // 60)
        return f"{h:02d}:{m:02d}:{s % 60:06.3f}".replace(".", ",")
    lines = []
    for i, c in enumerate(chunks):
        lines += [str(i + 1), f"{ts(i * step)} --> {ts((i + 1) * step)}", c, ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    return out

def render(script: dict, scene_images: list, audio: str, out: Path, scene_meta: list = None) -> dict:
    """scene_images: una imagen PIL por escena (layout). audio: ruta o None.
    scene_meta (opcional): lista paralela a scene_images con {"kb": "in"|"out"}
    para variar el Ken Burns (p. ej. imagen reutilizada en otra escena)."""
    fails = layout.validate_layout(script)
    if fails:
        raise layout.LayoutError("layout inválido: " + "; ".join(fails))
    audio_dur = probe_duration(audio) if audio and Path(audio).exists() else 0.0
    duration = audio_dur if audio_dur > 3 else float(script.get("estimated_seconds", 52) or 52)
    out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    srt = make_srt(script.get("full_text", ""), duration, out.parent / "captions.srt")
    chunks = layout.caption_chunks(script)
    total_words = sum(c["words"] for c in chunks) or 1
    tmp = out.parent / "_render_tmp"; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
    segments = []
    for i, ch in enumerate(chunks):
        scene_img = scene_images[min(ch["scene"], len(scene_images) - 1)]
        frame = layout.caption_overlay(scene_img, ch["text"])
        png = tmp / f"f{i:03d}.png"; frame.save(png)
        dur = max(0.7, duration * ch["words"] / total_words)
        seg = tmp / f"s{i:03d}.mp4"
        frames_n = max(20, int(dur * 30))
        kb = "in"
        if scene_meta:
            kb = (scene_meta[min(ch["scene"], len(scene_meta) - 1)] or {}).get("kb", "in")
        zexpr = "max(1.05-0.0011*on,1.0)" if kb == "out" else "min(1+0.0011*on,1.05)"
        vf = (f"scale=1188:2112,zoompan=z='{zexpr}':x='iw/2-(iw/zoom/2)':"
              f"y='ih/2-(ih/zoom/2)':d={frames_n}:s=1080x1920:fps=30,format=yuv420p")
        r = subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", str(png), "-vf", vf,
                            "-t", f"{dur:.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(seg)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            raise RuntimeError(f"ffmpeg segmento {i} falló: {r.stderr[-500:]}")
        segments.append(seg)
    concat = tmp / "concat.txt"
    concat.write_text("".join(f"file '{s.resolve()}'\n" for s in segments), encoding="utf-8")
    body = tmp / "body.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
                    "-c", "copy", str(body)], capture_output=True, text=True, check=True)
    if audio and Path(audio).exists():
        cmd = ["ffmpeg", "-y", "-i", str(body), "-i", str(audio), "-map", "0:v", "-map", "1:a",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", str(out)]
    else:
        cmd = ["ffmpeg", "-y", "-i", str(body), "-f", "lavfi", "-t", f"{duration:.2f}",
               "-i", "anullsrc=r=44100:cl=stereo", "-map", "0:v", "-map", "1:a",
               "-c:v", "copy", "-c:a", "aac", "-shortest", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    ok = r.returncode == 0 and out.exists()
    frames_info = extract_frames(out, out.parent) if ok else {"frames_generated": False}
    shutil.rmtree(tmp, ignore_errors=True)
    if not ok:
        raise RuntimeError(f"mux final falló: {r.stderr[-500:]}")
    if not frames_info.get("frames_generated"):
        raise RuntimeError("no se pudieron generar los cuadros de QC visual")
    return {"rendered": True, "out": str(out), "duration_sec": round(probe_duration(out), 2),
            "srt": str(srt), "caption_chunks": len(chunks), "frames": frames_info,
            "layout_version": 2, "uses_copyrighted_footage": False}
