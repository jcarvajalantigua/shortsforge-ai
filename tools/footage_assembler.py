#!/usr/bin/env python3
"""
footage_assembler.py — Assembler del ESTÁNDAR VIGENTE «metraje_real»
(orden del dueño 2026-10-20, MANDATO §3d; supersede a foto_real).

La pieza principal diaria se edita así:
  - METRAJE REAL de personas reales (clips de assets/footage/<tema>/ con
    manifest.json de procedencia). Nada animado, nada de diapositivas de
    texto, nada de fotos fijas con zoom como recurso principal.
  - EDICIÓN FLUIDA Y RESPIRABLE (corrección del dueño, 2026-10-20): cortes
    cada 4-6 s (promedio ~5 s) — un corte de metraje por cada ~2 trozos de
    subtítulo. Dentro del corte el plano es CONTINUO (mismo clip, offsets
    contiguos) y solo cambia el subtítulo por trozo; los clips del rol de
    la escena rotan por corte y el offset avanza (nunca un solo clip
    estirado). Crop vertical 1080x1920 SIN Ken Burns. El primer listón
    (corte por trozo, cada 2-4 s) se sentía DEMASIADO RÁPIDO y nada fluido.
  - TRANSICIONES SUAVES: fundido de 0.4-0.5 s SOLO en los bordes de cada
    corte (entrada del primer trozo, salida del último), no entre los
    trozos del mismo plano.
  - SOBRE EL VIDEO SOLO TITULARES CORTOS del guión (<=5 palabras por
    escena, layout.make_footage_overlay) + kicker de marca + subtítulos
    completos en su zona inferior.
  - VOZ en off a 1.20× (la genera tts_generator.py; aquí se usa el audio
    tal cual: este assembler NO altera el ritmo).
  - CAMA MUSICAL discreta SOLO si hay pista libre registrada
    (assets/music/manifest.json, layout.load_music_track): volumen 0.10
    bajo la voz, fundidos de entrada/salida y atribución en el manifiesto
    del paquete. Sin licencia clara registrada: sin música.
  - TARJETA DE CIERRE de ~2.5 s con el emblema vigente
    (branding/avatar-v2.png) sobre el verde oscuro del canal.

Al terminar genera los cuadros de QC visual (frames/ + contacto.png de
frames.py y hoja extendida con el cierre) y footage_manifest.json.

Sin manifiesto de metraje válido, el render FALLA con mensaje claro
(exit 3) — nunca se degrada a fotos, generadas ni iconos en silencio.

Uso:
    python3 tools/footage_assembler.py --script-json content/scripts/<slug>.json \
        --audio output/<slug>/voice.wav --out output/<slug>/short.mp4
"""
import argparse, json, shutil, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, load_json, load_config
import layout
from frames import extract_frames, probe_duration
import render_core

FADE = 0.45           # fundido suave en los bordes de cada corte (s); default — manda config (footage.fade_sec)
CUT_MIN_DEFAULT = 4.0  # un corte acumula trozos hasta esta duración (default — manda config: footage.cut_target_sec[0])
CARD_SEC_DEFAULT = 2.5

def _run(cmd: list) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script-json", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-music", action="store_true", help="fuerza render sin cama musical")
    args = ap.parse_args()
    script = load_json(args.script_json, {})
    fails = layout.validate_layout(script)
    if fails:
        print(json.dumps({"format": "metraje_real", "layout_version": 3,
                          "layout_failures": fails}, ensure_ascii=False, indent=2))
        sys.exit(2)
    vfails = layout.validate_footage(script)
    if vfails:
        print(json.dumps({"format": "metraje_real",
                          "error": "formato «metraje real» sin librería válida: el render NO cae a fotos, generadas ni iconos",
                          "footage_failures": vfails}, ensure_ascii=False, indent=2))
        sys.exit(3)
    audio = Path(args.audio)
    if not audio.exists():
        print(json.dumps({"format": "metraje_real", "error": f"audio no encontrado: {audio}"},
                         ensure_ascii=False, indent=2)); sys.exit(1)
    audio_dur = probe_duration(audio)
    if audio_dur <= 3:
        print(json.dumps({"format": "metraje_real", "error": f"audio demasiado corto: {audio_dur}s"},
                         ensure_ascii=False, indent=2)); sys.exit(1)
    cfg = load_config()
    prod = cfg.get("production", {}) if isinstance(cfg, dict) else {}
    fcfg = prod.get("footage", {}) if isinstance(prod, dict) else {}
    ccfg = fcfg.get("closing_card", {}) if isinstance(fcfg, dict) else {}
    fade = float(fcfg.get("fade_sec") or FADE)
    _ct = fcfg.get("cut_target_sec") or [CUT_MIN_DEFAULT, 6]
    cut_min, cut_max = float(_ct[0]), float(_ct[1])
    chunks_per_cut = int(fcfg.get("chunks_per_cut") or 2)
    card_sec = float(ccfg.get("seconds") or CARD_SEC_DEFAULT)
    brand = cfg.get("branding", {}) if isinstance(cfg, dict) else {}
    emblem_rel = ccfg.get("emblem") or brand.get("emblem") or "branding/avatar-v2.png"
    emblem = ROOT / emblem_rel
    card_title = ccfg.get("title") or (cfg.get("channel", {}) or {}).get("proposed_name") \
        or "Your Channel"
    card_line = ccfg.get("line") or "Síguenos — un video nuevo cada día"

    assigns, _ = layout.assign_footage(script)
    scenes = layout.effective_scenes(script)
    chunks = layout.caption_chunks(script)
    total_words = sum(c["words"] for c in chunks) or 1

    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    srt = render_core.make_srt(script.get("full_text", ""), audio_dur, out.parent / "captions.srt")
    tmp = out.parent / "_footage_tmp"; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)

    clip_durs, next_off, scene_rr = {}, {}, {}
    def clip_dur(path: Path) -> float:
        if path not in clip_durs:
            clip_durs[path] = probe_duration(path)
        return clip_durs[path]

    # Agrupación en CORTES (corrección del dueño, 2026-10-20): un corte de
    # metraje acumula trozos de subtítulo hasta alcanzar cut_min (config:
    # cut_target_sec[0], 4 s; en la práctica ~2 trozos por corte) para una
    # edición fluida y respirable. Si el resto final quedara < 3 s, se
    # fusiona con el corte anterior (el QC exige ningún corte < 3 s salvo
    # el gancho inicial). Dentro del corte el plano es continuo: mismo
    # clip con offsets contiguos; el subtítulo sigue cambiando por trozo.
    chunk_durs = [max(0.6, audio_dur * c["words"] / total_words) for c in chunks]
    groups, cur_g, cur_d = [], [], 0.0
    for ci, cdur in enumerate(chunk_durs):
        cur_g.append(ci); cur_d += cdur
        if cur_d >= cut_min:
            groups.append(cur_g); cur_g, cur_d = [], 0.0
    if cur_g:
        if groups and cur_d < 3.0:
            groups[-1].extend(cur_g)
        else:
            groups.append(cur_g)

    segments, seg_meta = [], []
    seg_n = 0
    for gidx, g in enumerate(groups):
        scene_idx = min(chunks[g[0]]["scene"], len(scenes) - 1)
        cands = assigns[scene_idx] or assigns[0]
        rr = scene_rr.get(scene_idx, 0); scene_rr[scene_idx] = rr + 1
        clip = cands[rr % len(cands)]
        gdur = sum(chunk_durs[ci] for ci in g)
        cd = clip_dur(clip["path"])
        off = next_off.get(clip["path"], 0.5)
        if off + gdur > cd - 0.25:
            off = 0.3
        next_off[clip["path"]] = off + gdur + 0.45
        cc = clip.get("crop_centering") or (0.5, 0.45)
        try:
            cx, cy = float(cc[0]), float(cc[1])
        except Exception:
            cx, cy = 0.5, 0.45
        elapsed = 0.0
        for j, ci in enumerate(g):
            ch = chunks[ci]
            dur = chunk_durs[ci]
            csc = min(ch["scene"], len(scenes) - 1)
            overlay = layout.make_footage_overlay(script, csc, ch["text"])
            opng = tmp / f"o{seg_n:03d}.png"; overlay.save(opng)
            seg = tmp / f"s{seg_n:03d}.mp4"
            # Fundidos SOLO en los bordes del corte: entrada en el primer
            # trozo y salida en el último; entre trozos, corte limpio
            # sobre el mismo plano continuo (nada de parpadeo).
            fades = []
            if j == 0:
                fades.append(f"fade=t=in:st=0:d={fade}")
            if j == len(g) - 1:
                fades.append(f"fade=t=out:st={max(0.05, dur - fade):.3f}:d={fade}")
            fchain = ",".join(fades) if fades else "null"
            vf = (f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
                  f"crop=1080:1920:(iw-1080)*{cx:.2f}:(ih-1920)*{cy:.2f},fps=30,setsar=1,"
                  f"format=yuv420p[base];[base][1:v]overlay=0:0[vv];"
                  f"[vv]{fchain}[v]")
            r = _run(["ffmpeg", "-y", "-ss", f"{off + elapsed:.2f}", "-i", str(clip["path"]),
                      "-i", str(opng), "-filter_complex", vf, "-map", "[v]", "-an",
                      "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "medium",
                      "-crf", "19", str(seg)])
            if r.returncode != 0:
                shutil.rmtree(tmp, ignore_errors=True)
                print(json.dumps({"format": "metraje_real",
                                  "error": f"ffmpeg segmento {seg_n} falló: {r.stderr[-400:]}"},
                                 ensure_ascii=False, indent=2)); sys.exit(1)
            segments.append(seg)
            elapsed += dur
            seg_n += 1
        seg_meta.append({"i": gidx, "scene": scene_idx + 1, "file": clip["file"],
                         "role": (scenes[scene_idx].get("image_role") or ""),
                         "offset_in": round(off, 2), "dur": round(gdur, 2),
                         "chunks": len(g),
                         "headline": layout.scene_titular(scenes[scene_idx])})

    # Tarjeta de cierre con el emblema vigente del canal.
    card_png = tmp / "card.png"
    layout.make_closing_card(emblem, card_title, card_line).save(card_png)
    card_seg = tmp / "card.mp4"
    r = _run(["ffmpeg", "-y", "-loop", "1", "-i", str(card_png),
              "-vf", f"fps=30,format=yuv420p,fade=t=in:st=0:d=0.30",
              "-t", f"{card_sec:.2f}", "-c:v", "libx264", "-preset", "medium",
              "-crf", "19", str(card_seg)])
    if r.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        print(json.dumps({"format": "metraje_real",
                          "error": f"tarjeta de cierre falló: {r.stderr[-400:]}"},
                         ensure_ascii=False, indent=2)); sys.exit(1)
    segments.append(card_seg)

    concat = tmp / "concat.txt"
    concat.write_text("".join(f"file '{s.resolve()}'\n" for s in segments), encoding="utf-8")
    body = tmp / "body.mp4"
    r = _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
              "-c", "copy", str(body)])
    if r.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        print(json.dumps({"format": "metraje_real", "error": f"concat falló: {r.stderr[-400:]}"},
                         ensure_ascii=False, indent=2)); sys.exit(1)

    total = audio_dur + card_sec
    music = None if args.no_music else layout.load_music_track()
    if music:
        fc = (f"[1:a]apad,atrim=0:{total:.3f}[voz];"
              f"[2:a]atrim=0:{total:.3f},volume=0.10,afade=t=in:st=0:d=1.0,"
              f"afade=t=out:st={max(0.1, total - 2.2):.3f}:d=2.2[mus];"
              f"[voz][mus]amix=inputs=2:duration=first:normalize=0[a]")
        cmd = ["ffmpeg", "-y", "-i", str(body), "-i", str(audio), "-i", str(music["path"]),
               "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)]
    else:
        fc = f"[1:a]apad,atrim=0:{total:.3f}[a]"
        cmd = ["ffmpeg", "-y", "-i", str(body), "-i", str(audio),
               "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)]
    r = _run(cmd)
    ok = r.returncode == 0 and out.exists()
    if not ok:
        shutil.rmtree(tmp, ignore_errors=True)
        print(json.dumps({"format": "metraje_real", "error": f"mux final falló: {r.stderr[-400:]}"},
                         ensure_ascii=False, indent=2)); sys.exit(1)

    frames_info = extract_frames(out, out.parent)
    # Cuadro extra del cierre + hoja extendida (inicio, 40%, mitad, 75%, cierre).
    try:
        from PIL import Image
        dur_out = probe_duration(out)
        extra = {"frame-40.png": dur_out * 0.40, "frame-75.png": dur_out * 0.75,
                 "frame-cierre.png": max(0.5, dur_out - 0.7)}
        fdir = out.parent / "frames"
        for name, t in extra.items():
            _run(["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(out),
                  "-frames:v", "1", str(fdir / name)])
        panels = ["frame-2s.png", "frame-40.png", "frame-mitad.png",
                  "frame-75.png", "frame-cierre.png"]
        imgs = []
        for p in panels:
            fp = fdir / p
            if fp.exists():
                imgs.append(Image.open(fp).resize((360, 640)))
        if len(imgs) == len(panels):
            sheet = Image.new("RGB", (360 * len(imgs), 640), "#000000")
            for j, im in enumerate(imgs):
                sheet.paste(im, (360 * j, 0))
            sheet.save(fdir / "contacto-extendida.png")
    except Exception:
        pass
    shutil.rmtree(tmp, ignore_errors=True)
    if not frames_info.get("frames_generated"):
        print(json.dumps({"format": "metraje_real",
                          "error": "no se pudieron generar los cuadros de QC visual"},
                         ensure_ascii=False, indent=2)); sys.exit(1)

    used, seen_files = [], set()
    for sm in seg_meta:
        if sm["file"] in seen_files:
            continue
        seen_files.add(sm["file"])
        for scene_cands in assigns:
            for v in scene_cands:
                if v["file"] == sm["file"]:
                    used.append({"file": v["file"], "roles": v["roles"],
                                 "source": v["source"], "source_url": v["source_url"],
                                 "license": v["license"], "author": v["author"]})
                    break
            else:
                continue
            break
    fdir, fdata = layout.load_footage_manifest(script)
    body_sec = sum(s["dur"] for s in seg_meta)
    manifest = {"format": "metraje_real", "layout_version": 3,
                "visual_language": "metraje REAL de personas reales (b-roll de oficina/actividad del tema) "
                                   "con cortes cada 4-6 s (edición fluida y respirable, ~2 trozos de "
                                   "subtítulo por corte, fundidos de 0.4-0.5 s solo en los bordes del "
                                   "corte); SOLO titulares cortos del guión sobre el video; "
                                   "subtítulos completos en la zona inferior; tarjeta de cierre con el "
                                   "emblema del canal; nada animado, nada de diapositivas de texto, "
                                   "sin fotos fijas con zoom",
                "footage_dir": str(fdir), "footage_manifest": str(fdir / "manifest.json"),
                "clips": used, "segments": seg_meta, "cuts": len(seg_meta),
                "avg_cut_sec": round(body_sec / max(1, len(seg_meta)), 2),
                "cut_target_sec": [cut_min, cut_max], "fade_sec": fade,
                "chunks_per_cut": chunks_per_cut, "sub_segments": seg_n,
                "body_sec": round(body_sec, 2),
                "headlines": [layout.scene_titular(s) for s in scenes],
                "voice": {"file": str(audio), "duration_sec": round(audio_dur, 2),
                          "rate_target": "1.20x (ver tts_manifest.json: rate_factor/length_scale)"},
                "music": ({"file": music["file"], "title": music["title"],
                           "author": music["author"], "source": music["source"],
                           "source_url": music["source_url"], "license": music["license"],
                           "attribution": music["attribution"], "volume": 0.10,
                           "role": "cama discreta bajo la voz"} if music else None),
                "closing_card": {"present": True, "seconds": card_sec,
                                 "emblem": str(emblem), "title": card_title, "line": card_line},
                "audio": str(audio), "rendered": True, "out": str(out),
                "duration_sec": round(probe_duration(out), 2),
                "srt": str(srt), "caption_chunks": len(chunks), "frames": frames_info,
                "uses_copyrighted_footage": False}
    (out.parent / "footage_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
