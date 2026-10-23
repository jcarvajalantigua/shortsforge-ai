#!/usr/bin/env python3
"""
clip_maker.py — MODO ESPEJO: video largo NUESTRO -> Shorts automáticos
multiplataforma (YouTube + TikTok). Decisión del dueño 2026-10-20:
«Lo que carguemos se hace short de videos largos» y «lo llevamos a TikTok».

Fuentes permitidas (y SOLO estas — lista blanca de config.yaml):
  - Archivo local: típicamente soltado en inbox-largos/ por nosotros.
  - URL de YouTube de un canal PROPIO listado en mirror_sources.own_channels
    (descarga con yt-dlp si está instalado). Un canal de terceros NUNCA es
    fuente espejo: republicar contenido ajeno = contenido reutilizado y el
    Partner Program se deniega. Por eso la lista blanca vacía RECHAZA toda URL.

Flujo:
  1. Transcripción local con timestamps por PALABRA:
     a) faster-whisper (instalado en .venv 2026-10-20, modelo de config,
        descarga ~150 MB la primera vez a la caché de HuggingFace), o
     b) fallback: SRT existente (--srt o captions.srt/<video>.srt junto al
        video), o corte manual (--start/--end con --title).
  2. Detección de mejores momentos: ventanas de 30-55 s alineadas a frases
     completas; puntúan gancho en los primeros segundos del clip (pregunta,
     número o promesa), densidad de información, cierre de frase y el score
     de retención del mini-guión resultante (retention_optimizer).
     Máx. N clips por largo (config mirror_sources.max_clips_per_long = 3),
     sin solaparse.
  3. Corte vertical 1080x1920: fuente horizontal -> fondo desenfocado que
     rellena + video centrado; fuente vertical -> escalado directo.
     Subtítulos quemados SOLO en la zona inferior (layout.caption_overlay,
     zona 72-92%, máx 2 líneas, márgenes medidos) y kicker SOLO en la zona
     superior (layout por zonas de tools/layout.py). NADA de texto en el centro.
  4. Paquete multiplataforma en output/clips/<slug>/:
     - short.mp4        MP4 maestro SIN marcas de agua (sirve a ambas).
     - metadata_youtube.json  título + descripción completa («Mira el video
       completo:», disclaimer, bloque «Fuentes:» si el largo traía noticia).
     - metadata_tiktok.json   texto corto + hashtags + ai_disclosure=true
       OBLIGATORIO (la voz es sintética; TikTok exige declarar contenido IA).
     - captions.srt, cover.png, frames/ (QC visual), package_manifest.json
       y guión del clip en content/scripts/clips/<slug>.json (lo exige el QC:
       mismas puertas que cualquier Short — zonas, retención >=70, anti-venta).

Uso:
    python3 tools/clip_maker.py --input inbox-largos/mi-video-largo.mp4
    python3 tools/clip_maker.py --input output/<paquete>/short.mp4 --test
    python3 tools/clip_maker.py --input video.mp4 --srt subs.srt --max-clips 2
    python3 tools/clip_maker.py --url https://youtube.com/watch?v=...  (solo lista blanca)
NO publica nada: deja paquetes listos para automation/qc.py y tools/uploader.py.
"""
import argparse, json, math, re, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, load_json, save_json, load_config, slugify  # noqa: E402
import layout  # noqa: E402  (medición por zonas: subtítulos y kicker)
import retention_optimizer  # noqa: E402
import title_thumbnail  # noqa: E402
from frames import extract_frames, probe_duration  # noqa: E402

STOPWORDS = set("""de la el en y a los del se las por un para con no una su al es lo como más pero sus le ya o este sí porque esta son entre cuando muy sin sobre también me hasta hay donde quien desde todo nos durante uno ni contra eso ante e esto mí antes algunos qué unos yo otro otras otra él tanto esa estos mucho quienes nada muchos cual poco ella estar estas algunas algo nosotros mi mis tu tus te ti tuyo tuya ellos ellas nosotras vosotros vosotras os mío mía míos mías tuyo nuestro nuestras nuestros vuestro vuestra vuestros vuestras ese esa eso esos esas aquel aquella aquello aquellos aquellas esto está están ser es son fue fueron era hace hacen tener tiene tienen tenido puede pueden debe deben ir va van""".split())
PROMISE_MARKERS = retention_optimizer.PROMISE_MARKERS
PAYOFF_MARKERS = retention_optimizer.PAYOFF_MARKERS

# ---------------------------------------------------------------- transcripción
def parse_srt(path: Path) -> list[dict]:
    """SRT -> segmentos {start, end, text, words:[{w,start,end}]} con tiempos
    de palabra interpolados de forma uniforme dentro de cada bloque."""
    raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    def ts(s):
        h, m, rest = s.split(":"); sec, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000.0
    segs = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [ln for ln in block.strip().splitlines() if ln.strip()]
        m = None
        for ln in lines:  # buscar la línea de tiempos (no asumir que es la primera)
            m = re.match(r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})", ln)
            if m: break
        if not m: continue
        start, end = ts(m.group(1)), ts(m.group(2))
        text = " ".join(ln for ln in lines if "-->" not in ln and not ln.strip().isdigit()).strip()
        words = text.split()
        if not words: continue
        step = (end - start) / len(words)
        segs.append({"start": start, "end": end, "text": text,
                     "words": [{"w": w, "start": start + i * step, "end": start + (i + 1) * step}
                               for i, w in enumerate(words)]})
    return segs

def _load_audio_samples(media: Path):
    """Decodifica el audio a float32 mono 16 kHz con ffmpeg y lo devuelve
    como numpy array, SIN pasar por PyAV.

    Por qué: faster-whisper 1.2.1 (audio.py:46) decodifica las RUTAS con
    `av.open(input_file, mode="r", metadata_errors="ignore")`, pero el PyAV
    instalado (av 19.0.1) ya NO acepta el kwarg `metadata_errors` en open()
    -> TypeError: open() got an unexpected keyword argument 'metadata_errors'
    y TODA transcripción por ruta explotaba (clip_maker caía en silencio al
    fallback SRT). Pasándole a transcribe() un array numpy, faster-whisper
    lo usa directo (decode_audio devuelve los arrays tal cual) y PyAV no
    interviene. Verificado 2026-10-20; detalle en LOG.md."""
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(media), "-vn",
                        "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                       capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype=np.float32).copy()

def transcribe_whisper(media: Path, model_name: str, language: str) -> list[dict]:
    """faster-whisper local con word_timestamps. Lanza ImportError si no está."""
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(_load_audio_samples(media),
                                       language=language or None,
                                       word_timestamps=True, vad_filter=True)
    out = []
    for s in segments:
        words = [{"w": w.word.strip(), "start": float(w.start), "end": float(w.end)}
                 for w in (s.words or []) if w.word.strip()]
        if not words:  # sin palabras: un pseudo-token por el segmento
            words = [{"w": t, "start": float(s.start), "end": float(s.end)} for t in s.text.split()]
        out.append({"start": float(s.start), "end": float(s.end), "text": s.text.strip(), "words": words})
    return out

def extract_audio(media: Path, tmp: Path) -> Path:
    wav = tmp / "audio.wav"
    subprocess.run(["ffmpeg", "-y", "-i", str(media), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
                   capture_output=True, text=True, check=True)
    return wav

# ---------------------------------------------------------------- momentos
def flatten_words(segments: list[dict]) -> list[dict]:
    words = [w for s in segments for w in s["words"]]
    words.sort(key=lambda w: w["start"])
    for i, w in enumerate(words):
        w["ends_sentence"] = bool(re.search(r"[.?!…]$", w["w"])) or i == len(words) - 1
        w["starts_sentence"] = (i == 0) or words[i - 1]["ends_sentence"]
    return words

def _hook_bonus(words: list[dict], start_idx: int) -> tuple[float, str]:
    head = " ".join(w["w"] for w in words[start_idx:start_idx + 18])
    low = head.lower()
    if "¿" in head or "?" in head: return 30.0, "pregunta en el arranque"
    if re.search(r"\d", head): return 26.0, "dato con número en el arranque"
    if any(m in low for m in PROMISE_MARKERS): return 22.0, "promesa concreta en el arranque"
    if low.startswith(("hola", "bienvenidos", "en este video")): return -25.0, "arranque con saludo (débil)"
    return 6.0, "arranque neutro"

def build_clip_script(topic: str, clip_words: list[dict], dur: float, kicker: str) -> dict:
    """Mini-guión del clip desde su transcripción real (lo puntúa el QC con el
    MISMO retention_optimizer de cualquier Short)."""
    text = " ".join(w["w"] for w in clip_words).strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]
    if not sentences: sentences = [text]
    hook_parts, acc = [], 0
    for s in sentences:  # gancho = 1-2 primeras frases (convención del proyecto)
        hook_parts.append(s); acc += len(s.split())
        if acc >= 14 or len(hook_parts) == 2: break
    hook = " ".join(hook_parts)
    rest = sentences[len(hook_parts):]
    cierre, desarrollo = "", []
    if rest:
        cierre = rest[-1]; middle = rest[:-1]
        if middle:
            per = math.ceil(len(middle) / 3)
            desarrollo = [" ".join(middle[i:i + per]) for i in range(0, len(middle), per)][:3]
        elif len(sentences) > len(hook_parts):
            desarrollo = []
    script = {"topic": topic, "kind": "mirror-clip", "mode": "espejo-desde-largo",
              "sections": {"hook_0_3s": hook, "desarrollo": desarrollo, "cierre_cta": cierre},
              "full_text": text, "word_count": len(text.split()),
              "estimated_seconds": round(dur, 1), "kicker": kicker,
              "scenes_visual": _scenes(topic, 1 + len(desarrollo) + (1 if cierre else 0)),
              "disclaimer": "Esto es educación general, no asesoría financiera personalizada."}
    return script

def _scenes(topic: str, n: int) -> list[dict]:
    """Dato grande para los asserts de layout (en espejo el visual es el video
    real; esto solo alimenta la medición de layout.py)."""
    big = ""
    m = re.search(r"(\d{1,2}) de (enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)", topic.lower())
    if m: big = f"{m.group(1)} {m.group(2)[:3].upper()}"
    elif re.search(r"\d+\s?%", topic): big = re.search(r"\d+[\.,]?\d*\s?%", topic).group(0).replace(" ", "")
    elif re.search(r"\d", topic): big = re.search(r"\d[\d\.,]*", topic).group(0)
    else:
        words = [w for w in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,}", topic) if w.lower() not in STOPWORDS]
        big = " ".join(words[:2]).upper() or "EN USA"
    return [{"big": big, "support": "", "icon": "grafica"} for _ in range(max(1, n))]

def find_moments(words: list[dict], topic: str, kicker: str,
                 min_sec: float, max_sec: float, max_clips: int) -> list[dict]:
    cands = []
    n = len(words)
    for i, w in enumerate(words):
        if not w["starts_sentence"]: continue
        best = None
        for j in range(i, n):
            dur = words[j]["end"] - w["start"]
            if dur > max_sec: break
            if dur >= min_sec and words[j]["ends_sentence"]:
                best = j  # ventana más larga que cierra en fin de frase
        if best is None: continue
        seg = words[i:best + 1]
        dur = seg[-1]["end"] - seg[0]["start"]
        hb, why = _hook_bonus(words, i)
        wps = len(seg) / max(dur, 0.1)
        density = 14.0 if 2.0 <= wps <= 3.3 else (7.0 if 1.6 <= wps < 2.0 or 3.3 < wps <= 3.8 else 0.0)
        content_ratio = sum(1 for x in seg if re.sub(r"[^a-záéíóúñ]", "", x["w"].lower()) not in STOPWORDS) / len(seg)
        low = " ".join(x["w"] for x in seg).lower()
        payoff = 8.0 if any(p in low[int(len(low) * 0.4):] for p in PAYOFF_MARKERS) else 0.0
        script = build_clip_script(topic, seg, dur, kicker)
        ret = retention_optimizer.score_script(script)["score"]
        score = hb + density + content_ratio * 20 + payoff + ret * 0.4
        cands.append({"start": seg[0]["start"], "end": seg[-1]["end"], "dur": dur,
                      "words": seg, "score": round(score, 1), "hook_kind": why,
                      "retention": ret, "script": script})
    cands.sort(key=lambda c: -c["score"])
    chosen, taken = [], []
    for c in cands:
        if len(chosen) >= max_clips: break
        if any(not (c["end"] <= t[0] or c["start"] >= t[1]) for t in taken): continue
        chosen.append(c); taken.append((c["start"], c["end"]))
    return sorted(chosen, key=lambda c: c["start"])

# ---------------------------------------------------------------- render vertical
def _hex_rgba(h: str, a: int = 255):
    h = h.lstrip("#"); return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)

def kicker_overlay_png(kicker: str, out: Path):
    """Pastilla de marca SOLO en la zona superior (mismas medidas que layout._base)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (layout.W, layout.H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = (kicker or "DINERO EN USA").upper()
    size = layout.fit_font_size(d, k, layout.TEXT_MAX_W - 160, 44, 30)
    tw = layout.text_w(d, k, size)
    pw, ph = tw + 72, 92
    x0, y0 = (layout.W - pw) / 2, 120
    d.rounded_rectangle([x0, y0, x0 + pw, y0 + ph], radius=46, fill=_hex_rgba(layout.PANEL))
    d.ellipse([x0 + 28, y0 + ph / 2 - 9, x0 + 46, y0 + ph / 2 + 9], fill=_hex_rgba(layout.ACCENT))
    bbox = d.textbbox((0, 0), k, font=layout.font(size))
    d.text((x0 + 62, y0 + ph / 2 - (bbox[3] - bbox[1]) / 2 - bbox[1]), k,
           font=layout.font(size), fill=_hex_rgba(layout.WHITE))
    img.save(out); return out

def _caption_overlay_rgba(text: str):
    """La pastilla de subtítulo de layout.caption_overlay, pero sobre lienzo
    TRANSPARENTE (para superponerla al video real del espejo). Misma geometría
    y mismas mediciones PIL que layout.py: zona inferior 72-92%, <=2 líneas,
    márgenes medidos. Si el trozo no cabe -> LayoutError, igual que el original."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (layout.W, layout.H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    size = 60
    lines = layout.wrap_measured(d, text, size, layout.TEXT_MAX_W)
    if len(lines) > 2: raise layout.LayoutError(f"subtítulo de {len(lines)} líneas: {text!r}")
    lh = 76
    tw = max(layout.text_w(d, ln, size) for ln in lines)
    pw, ph = tw + 64, len(lines) * lh + 44
    zone_h = layout.ZONE_SUB[1] - layout.ZONE_SUB[0]
    if ph > zone_h: raise layout.LayoutError("pastilla de subtítulo más alta que su zona")
    x0 = (layout.W - pw) / 2; y0 = layout.ZONE_SUB[0] + (zone_h - ph) / 2
    d.rounded_rectangle([x0, y0, x0 + pw, y0 + ph], radius=28, fill=(0, 0, 0, 178))
    y = y0 + 22
    for ln in lines:
        lw = layout.text_w(d, ln, size)
        bbox = d.textbbox((0, 0), ln, font=layout.font(size))
        d.text(((layout.W - lw) / 2, y - bbox[1]), ln, font=layout.font(size), fill=(255, 255, 255, 255))
        y += lh
    return img

def caption_pngs(clip_words: list[dict], clip_start: float, tmp: Path) -> list[tuple[Path, float, float]]:
    """Un PNG transparente por trozo de subtítulo, troceado como en
    layout.caption_chunks (<=2 líneas a 60 px en TEXT_MAX_W, <=9 palabras)."""
    out = []
    cur: list[dict] = []
    def flush():
        if not cur: return
        text = " ".join(w["w"] for w in cur)
        p = tmp / f"cap{len(out):03d}.png"
        _caption_overlay_rgba(text).save(p)
        out.append((p, cur[0]["start"] - clip_start, cur[-1]["end"] - clip_start))
    def fits(ws):
        from PIL import Image, ImageDraw
        d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        return len(layout.wrap_measured(d, " ".join(w["w"] for w in ws), 60, layout.TEXT_MAX_W)) <= 2
    for w in clip_words:
        trial = cur + [w]
        if cur and (not fits(trial) or len(trial) > 9):
            flush(); cur = [w]
        else:
            cur = trial
    flush()
    return out

def probe_size(path: Path) -> tuple[int, int]:
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        # OJO: este ffprobe emite "1080,1920," (coma FINAL) en csv: hay que
        # filtrar campos vacíos o el desempaque falla y devuelve (0,0) —
        # así se saltó la guardia de fuente en su primera prueba (2026-10-20).
        fields = [f for f in p.stdout.strip().replace("\n", ",").split(",") if f.strip()]
        return int(fields[0]), int(fields[1])
    except Exception:
        return 0, 0

def render_clip(source: Path, cand: dict, out_mp4: Path, kicker: str, tmp: Path) -> dict:
    start, end, dur = cand["start"], cand["end"], cand["dur"]
    sw, sh = probe_size(source)
    kick = kicker_overlay_png(kicker, tmp / "kicker.png")
    caps = caption_pngs(cand["words"], start, tmp)
    inputs = ["-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(source)]
    for png, _a, _b in [(kick, 0, 0)] + caps:
        inputs += ["-loop", "1", "-framerate", "30", "-i", str(png)]
    if (sw, sh) == (1080, 1920):
        chain = "[0:v]scale=1080:1920,setsar=1[base]"
    elif sw > sh:  # horizontal: fondo desenfocado + video centrado
        chain = ("[0:v]split[sa][sb];"
                 "[sa]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=42[bg];"
                 "[sb]scale=1080:-2[fgr];[bg][fgr]overlay=(W-w)/2:(H-h)/2[base]")
    else:  # vertical de otra resolución: relleno por recorte
        chain = "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[base]"
    last, filters = "base", [chain]
    overlays = [(1, None, None)] + [(i + 2, a, b) for i, (_p, a, b) in enumerate(caps)]
    for idx, a, b in overlays:
        lbl = f"v{idx}"
        en = "" if a is None else f":enable='between(t,{a:.2f},{max(a + 0.35, b):.2f})'"
        filters.append(f"[{last}][{idx}:v]overlay=0:0:format=auto{en}[{lbl}]")
        last = lbl
    filters.append(f"[{last}]format=yuv420p[vout]")
    cmd = (["ffmpeg", "-y"] + inputs + ["-filter_complex", ";".join(filters),
           "-map", "[vout]", "-map", "0:a?", "-c:v", "libx264", "-preset", "medium",
           "-crf", "20", "-c:a", "aac", "-b:a", "128k", "-t", f"{dur:.3f}",
           "-movflags", "+faststart", str(out_mp4)])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out_mp4.exists():
        raise RuntimeError(f"ffmpeg clip falló: {r.stderr[-600:]}")
    return {"duration_sec": round(probe_duration(out_mp4), 2), "caption_chunks": len(caps),
            "source_size": f"{sw}x{sh}"}

def make_clip_srt(clip_words: list[dict], clip_start: float, out: Path):
    chunks = [" ".join(w["w"] for w in clip_words[i:i + 7]) for i in range(0, len(clip_words), 7)]
    bounds = [(clip_words[i]["start"] - clip_start,
               clip_words[min(i + 6, len(clip_words) - 1)]["end"] - clip_start)
              for i in range(0, len(clip_words), 7)]
    def ts(s):
        s = max(0.0, s); h, m = int(s // 3600), int((s % 3600) // 60)
        return f"{h:02d}:{m:02d}:{s % 60:06.3f}".replace(".", ",")
    lines = []
    for i, (c, (a, b)) in enumerate(zip(chunks, bounds)):
        lines += [str(i + 1), f"{ts(a)} --> {ts(b)}", c, ""]
    out.write_text("\n".join(lines), encoding="utf-8"); return out

# ---------------------------------------------------------------- metadatos
def build_metadata(topic: str, script: dict, source_title: str, source_ref: str,
                   news: dict | None, out_dir: Path, test: bool) -> tuple[dict, dict]:
    hook = script["sections"]["hook_0_3s"]
    title = title_thumbnail.make_title(hook if len(hook) <= 90 else topic)
    yt_desc = title_thumbnail.make_description(title, script["full_text"][:220], news)
    full_line = (f"Mira el video completo: {source_ref}" if source_ref.startswith("http")
                 else f"Mira el video completo: [ENLACE-VIDEO-LARGO-PENDIENTE] (fuente local: {source_ref})")
    if "Recursos gratis sobre este tema:" in yt_desc:
        yt_desc = yt_desc.replace("Recursos gratis sobre este tema:",
                                  full_line + "\n\nRecursos gratis sobre este tema:", 1)
    else:
        yt_desc = full_line + "\n\n" + yt_desc
    yt = {"title": title, "title_chars": len(title), "description": yt_desc,
          "tags": ["finanzas personales en español", "dinero en usa", "credito en usa",
                   "llc en español", "negocios hispanos", "ia para negocios",
                   "educacion financiera", "hispanos en usa"],
          "category_id": 27, "language": "es", "privacy_default": "private",
          "made_for_kids": False, "contains_copyrighted_footage": False,
          "source_long_video": source_ref, "source_long_title": source_title,
          "platform": "youtube"}
    if news: yt["news"] = news
    cover = title_thumbnail.make_cover(title, out_dir / "cover.png", load_config())
    yt["cover"] = str(cover)
    # TikTok: texto corto, hashtags y declaración de IA OBLIGATORIA (voz Piper).
    tag_topic = title_thumbnail._resource_tag(topic)
    extra = {"CREDITO": "#CreditoUSA", "IMPUESTOS": "#ImpuestosUSA", "IA": "#IAparaNegocios"}.get(tag_topic, "#NegociosUSA")
    tt_caption = (hook.strip()[:150] + f"\n#DineroEnUSA #FinanzasPersonales {extra} #Shorts").strip()
    tt = {"caption": tt_caption, "caption_chars": len(tt_caption),
          "hashtags": ["#DineroEnUSA", "#FinanzasPersonales", extra, "#Shorts"],
          "ai_disclosure": True,   # OBLIGATORIO: voz sintética / contenido con apoyo de IA
          "ai_disclosure_label": "Contenido creado con apoyo de IA (voz sintética)",
          "contains_ai_generated_content": True,
          "platform": "tiktok", "privacy_default": "private",
          "source_long_video": source_ref,
          "upload_status": "pendiente_conexion (ver tiktok en config.yaml y tools/uploader.py)"}
    return yt, tt

# ---------------------------------------------------------------- entrada URL
def download_whitelisted(url: str, cfg: dict, tmp: Path) -> Path:
    wl = [str(w) for w in (((cfg.get("mirror_sources") or {}).get("own_channels")) or []) if str(w).strip()]
    if not wl or not any(w in url for w in wl):
        raise SystemExit(json.dumps({"error": "URL rechazada: el canal no está en la lista blanca "
                                     "mirror_sources.own_channels de config.yaml. El modo espejo SOLO "
                                     "procesa canales propios; nunca canales de terceros."}, ensure_ascii=False))
    import shutil
    if not shutil.which("yt-dlp"):
        raise SystemExit(json.dumps({"error": "yt-dlp no está instalado: no se puede descargar de YouTube. "
                                     "Instálalo (pip install yt-dlp) o suelta el archivo en inbox-largos/."},
                                    ensure_ascii=False))
    r = subprocess.run(["yt-dlp", "-f", "bv*+ba/b", "-o", str(tmp / "fuente.%(ext)s"), url],
                       capture_output=True, text=True)
    got = sorted(tmp.glob("fuente.*"))
    if r.returncode != 0 or not got:
        raise SystemExit(json.dumps({"error": f"yt-dlp falló: {r.stderr[-300:]}"}, ensure_ascii=False))
    return got[0]

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Modo espejo: largo nuestro -> Shorts YouTube+TikTok")
    ap.add_argument("--input", help="archivo de video largo local (nuestro)")
    ap.add_argument("--url", help="URL de video de un canal PROPIO en la lista blanca")
    ap.add_argument("--srt", help="SRT existente (fallback si no hay whisper)")
    ap.add_argument("--start", type=float, help="corte manual: inicio (s) — exige --end y --title")
    ap.add_argument("--end", type=float)
    ap.add_argument("--title", help="título/tema del video largo fuente")
    ap.add_argument("--kicker", default="DINERO EN USA", help="pastilla superior, máx 5 palabras")
    ap.add_argument("--source-url", default="", help="URL pública del video largo (para «Mira el video completo:»)")
    ap.add_argument("--max-clips", type=int, default=None)
    ap.add_argument("--out-dir", default=str(ROOT / "output" / "clips"))
    ap.add_argument("--test", action="store_true", help="marca los paquetes como PRUEBA de mecánica")
    ap.add_argument("--force", action="store_true",
                    help="permite procesar una fuente sospechosa de ya estar editada (vertical <90 s) en modo normal")
    args = ap.parse_args()
    cfg = load_config()
    mcfg = cfg.get("mirror_sources") or {}
    min_sec = float(mcfg.get("clip_min_sec") or 30); max_sec = float(mcfg.get("clip_max_sec") or 55)
    max_clips = args.max_clips or int(mcfg.get("max_clips_per_long") or 3)
    import tempfile, shutil
    tmp = Path(tempfile.mkdtemp(prefix="clipmaker-"))
    try:
        if args.url:
            source = download_whitelisted(args.url, cfg, tmp)
            source_ref = args.url
        elif args.input:
            source = Path(args.input)
            if not source.exists():
                print(json.dumps({"error": f"no existe el archivo: {source}"}, ensure_ascii=False)); sys.exit(2)
            source_ref = args.source_url or str(source)
        else:
            ap.error("usa --input o --url")
        # GUARDIA DE FUENTE (2026-10-20): un vertical 9:16 de <90 s casi seguro
        # es un Short YA EDITADO (con kicker/subtítulos quemados), no un máster
        # limpio: si se usa como "largo", el clip hereda esas capas y las
        # duplica con las del espejo (pasó en la prueba real de hoy). La
        # bandeja espejo recibe MÁSTERES LIMPIOS. En modo normal se BLOQUEA
        # (salvo --force); en --test se deja pasar pero el paquete y la salida
        # quedan marcados con la advertencia.
        SOURCE_WARNING = "fuente probablemente ya editada — verificar textos quemados"
        source_warning = None
        _sw, _sh = probe_size(source)
        _sdur = probe_duration(source)
        if _sh > _sw > 0 and _sdur < 90:
            source_warning = SOURCE_WARNING
            if not args.test and not args.force:
                print(json.dumps({"error": f"Bloqueado por guardia de fuente: {_sw}x{_sh}, "
                                  f"{_sdur:.0f} s — {SOURCE_WARNING}. El modo espejo espera "
                                  "másters limpios (sin subtítulos ni textos quemados). "
                                  "Si es intencional, repite con --force.",
                                  "source_warning": SOURCE_WARNING}, ensure_ascii=False))
                sys.exit(2)
        # Noticias/fuentes si la fuente es un paquete del pipeline (output/<slug>/)
        news, source_pkg_meta = None, {}
        sib = source.parent / "metadata.json"
        if sib.exists():
            source_pkg_meta = load_json(sib, {}) or {}
            news = source_pkg_meta.get("news")
        source_title = args.title or source_pkg_meta.get("title") or source.stem.replace("-", " ")
        transcript_src, segments = None, []
        if args.start is not None and args.end is not None:
            transcript_src = "manual"
        else:
            srt_path = Path(args.srt) if args.srt else next(
                (p for p in (source.parent / "captions.srt", source.with_suffix(".srt")) if p.exists()), None)
            try:
                audio = extract_audio(source, tmp)
                segments = transcribe_whisper(audio, str(mcfg.get("whisper_model") or "base"),
                                              str(mcfg.get("whisper_language") or "es"))
                transcript_src = "faster-whisper"
            except ImportError:
                if srt_path: segments, transcript_src = parse_srt(srt_path), f"srt:{srt_path.name}"
            except Exception as e:
                if srt_path: segments, transcript_src = parse_srt(srt_path), f"srt-fallback-tras-error-whisper:{e}"
                else: raise
            if not segments and srt_path:
                segments, transcript_src = parse_srt(srt_path), f"srt:{srt_path.name}"
        words = flatten_words(segments) if segments else []
        if args.start is not None and args.end is not None:
            if not words:
                print(json.dumps({"error": "corte manual sin transcripción: aporta --srt para subtitular"}, ensure_ascii=False)); sys.exit(2)
            sel = [w for w in words if args.start <= w["start"] < args.end]
            cands = [{"start": sel[0]["start"], "end": sel[-1]["end"], "dur": sel[-1]["end"] - sel[0]["start"],
                      "words": sel, "score": 0, "hook_kind": "manual", "retention": None,
                      "script": build_clip_script(source_title, sel, sel[-1]["end"] - sel[0]["start"], args.kicker)}]
        else:
            if not words:
                print(json.dumps({"error": "sin transcripción: faster-whisper no disponible y no hay SRT"}, ensure_ascii=False)); sys.exit(2)
            cands = find_moments(words, source_title, args.kicker, min_sec, max_sec, max_clips)
        if not cands:
            print(json.dumps({"error": "ningún momento cumple 30-55 s con frase completa y gancho",
                              "transcript_source": transcript_src}, ensure_ascii=False)); sys.exit(1)
        results = []
        base_out = Path(args.out_dir); base_out.mkdir(parents=True, exist_ok=True)
        for i, cand in enumerate(cands, 1):
            script = cand["script"]
            slug = ("test-" if args.test else "") + slugify(
                f"clip {source_title} {script['sections']['hook_0_3s'][:38]}", 56) + f"-{i}"
            pkg = base_out / slug; pkg.mkdir(parents=True, exist_ok=True)
            ctmp = tmp / f"c{i}"; ctmp.mkdir()
            info = render_clip(source, cand, pkg / "short.mp4", args.kicker, ctmp)
            make_clip_srt(cand["words"], cand["start"], pkg / "captions.srt")
            script_path = ROOT / "content" / "scripts" / "clips" / f"{slug}.json"
            save_json(script_path, script)
            yt, tt = build_metadata(source_title, script, source_title, source_ref, news, pkg, args.test)
            save_json(pkg / "metadata_youtube.json", yt)
            save_json(pkg / "metadata_tiktok.json", tt)
            frames_info = extract_frames(pkg / "short.mp4", pkg)
            manifest = {"slug": slug, "kind": "mirror-clip", "test": bool(args.test),
                        "source_warning": source_warning,
                        "script": str(script_path), "master_mp4": "short.mp4",
                        "platforms": ["youtube", "tiktok"],
                        "source": {"file": str(source), "ref": source_ref, "title": source_title,
                                   "window_sec": [round(cand["start"], 2), round(cand["end"], 2)],
                                   "transcript_source": transcript_src},
                        "moment": {"score": cand["score"], "hook_kind": cand["hook_kind"],
                                   "retention_score": cand.get("retention")},
                        "render": info, "frames": frames_info,
                        "contains_copyrighted_footage": False}
            save_json(pkg / "package_manifest.json", manifest)
            results.append({"package": str(pkg), "slug": slug, "duration_sec": info["duration_sec"],
                            "moment_score": cand["score"], "retention": cand.get("retention"),
                            "frames_generated": frames_info.get("frames_generated")})
        out_json = {"ok": True, "source": str(source), "transcript_source": transcript_src,
                    "clips": results}
        if source_warning: out_json["source_warning"] = source_warning
        print(json.dumps(out_json, ensure_ascii=False, indent=2))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    main()
