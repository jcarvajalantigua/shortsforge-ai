#!/usr/bin/env python3
"""
qc.py — Control de calidad de paquetes (puerta a ready/). Ver AUTONOMIA.md y MANDATO.md.

Un paquete SOLO pasa a ready/ si cumple TODO:
  - short.mp4 válido (ffprobe): 1080x1920, duración 20-95 s.
  - Audio REAL, no silencio: volumedetect mean_volume > -45 dB y max_volume > -20 dB.
  - Subtítulos: captions.srt presente con al menos 5 bloques.
  - Título <= 100 caracteres (metadata.json).
  - Disclaimer presente en la descripción (metadata.json).
  - Sin venta directa ni promesas prohibidas (MANDATO.md) en guión ni descripción:
    patrones de precio con $, compra/contrata imperativos de venta, oferta,
    descuento, checkout, enlace de pago, código promocional, urgencia de venta,
    «rendimiento garantizado», «hazte rico», «sin riesgo».
  - Score de retención >= 70 (tools/retention_optimizer.py).
  - LAYOUT POR ZONAS (corrección 2026-10-20, tools/layout.py): kicker <=5
    palabras, dato grande y apoyo que CABEN medidos con PIL, subtítulos que
    envuelven a <=2 líneas en su zona. El título completo jamás va quemado.
  - FUENTES (corrección 2026-10-20): si la pieza es de actualidad (guión con
    news), metadata.news debe traer source_url http(s) y la descripción debe
    incluir el bloque «Fuentes:» con esa URL. Sin fuente con URL = RECHAZO.
  - QC VISUAL (corrección 2026-10-20): frames/ con 3 cuadros extraídos
    (2 s, mitad, penúltimo) + hoja de contacto contacto.png. Sin capturas el
    paquete NO pasa: la falla original fue no mirar los videos.
  - FORMATO «FOTO REAL» (orden del dueño 2026-10-20, sustituye a la imagen
    generada por IA y a la iconografía flat): si el guión declara
    format=foto_real (alias histórico aceptado: imagen_generada), debe existir
    assets/real/<tema>/manifest.json con procedencia completa (fuente, URL de
    origen, licencia libre/dominio público, autor, dimensiones), UNA foto real
    por escena con resolución suficiente para el crop vertical, y el
    animated_manifest.json del paquete debe declarar format=foto_real con la
    lista de fotos usadas y su procedencia. Sin manifiesto de fotos reales =
    RECHAZO (el render además falla antes: nunca se cae a generadas ni a
    iconos en silencio). [foto_real quedó SUPERSEDIDO como estándar por
    metraje_real; este check se mantiene para paquetes legados.]
  - FORMATO «METRAJE REAL» (ESTÁNDAR VIGENTE, orden del dueño 2026-10-20,
    MANDATO §3d; supersede a foto_real): si el guión declara
    format=metraje_real, debe existir assets/footage/<tema>/manifest.json con
    procedencia completa por clip (fuente, URL de origen, licencia libre,
    autor, dimensiones y duración que coinciden con el archivo por ffprobe),
    >= 1 clip por rol de escena y >= 3 clips por tema; el paquete trae
    footage_manifest.json con format=metraje_real, los clips usados con su
    procedencia, el ritmo declarado (cut_target_sec) y los segmentos de la
    edición: CORTES cada 4-6 s — edición fluida y respirable (corrección
    del dueño 2026-10-20: el listón original de 2-4 s se sentía demasiado
    rápido y nada fluido) — promedio 3.8-6.5 s, ningún corte < 3 s (salvo
    el gancho inicial) y >= 8 cortes. Además:
      · VOZ A 1.20×: tts_manifest.json registra length_scale == config
        (calibrado) y la duración real de la voz (duración total menos la
        tarjeta de cierre) es consistente con el ritmo 1.20× EFECTIVO sobre
        la base medida de la voz (167 ppm a 1.0×): ±12%.
      · TARJETA DE CIERRE presente: ~2-3.5 s, con el emblema vigente
        (branding/avatar-v2.png) registrado en footage_manifest.json.
      · CAMA MUSICAL solo si está registrada con licencia clara (fuente,
        URL y licencia en footage_manifest.music); sin registro, el paquete
        debe declarar music=null (sin música antes que una pista dudosa).
  - MARCO DE ALCANCE (orden del dueño 2026-10-20, content/marco-alcance.md;
    aplica a guiones NUEVOS desde hoy — las piezas anteriores pueden fallar
    estos checks y eso queda registrado, no reescrito): 4 checks sobre el
    guión, en TODOS los formatos:
      · hook_sin_contexto: la primera frase abre en 0-2 s con pregunta,
        número o promesa concreta en sus primeras ~10 palabras y SIN
        palabras de saludo/contexto («hola», «bienvenidos», «en este
        video», «hoy vamos a»…): debe funcionar para quien nunca vio el canal.
      · jerga_explicada: cada término del nicho presente (APR, LLC, EIN,
        IRA, tramo, prima) va explicado en lenguaje simple dentro de la
        misma pieza, salvo términos en ASSUMED_TERMS (hoy: ninguno).
      · senal_objetivo: el guión declara su señal (guardados / compartidos
        / comentarios / suscripcion) y el texto lleva su disparador.
      · cierre_loop: la última frase conecta con la promesa del hook
        (pregunta de vuelta o palabras clave compartidas): replay natural.
    Con estos 4, un paquete estándar suma 22 checks (los paquetes espejo
    añaden sus 5 puertas de TikTok/fuente: 27).
  - PAQUETES ESPEJO (output/clips/, modo espejo 2026-10-20): si el paquete trae
    metadata_youtube.json en vez de metadata.json, se aplican LAS MISMAS
    puertas (el guión del clip vive en content/scripts/clips/ y lo enlaza el
    package_manifest) y además: metadata_tiktok.json presente, con
    ai_disclosure=true y etiqueta (la voz es sintética: TikTok lo exige),
    caption <= 2.200 caracteres, >= 3 hashtags y anti-venta también sobre el
    texto de TikTok. El MP4 maestro es el mismo short.mp4 para ambas.
Además informa publish_ready: sin placeholders [RECURSO-GRATIS-...] sin resolver
en la descripción (la interconexión se conecta tras crear el canal).

Uso: python3 automation/qc.py --package output/<slug>
Salida: JSON {passed, publish_ready, checks, failures} y qc.json en el paquete.
"""
import argparse, json, re, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from common import load_json  # noqa: E402
import retention_optimizer  # noqa: E402
import layout as layout_mod  # noqa: E402

BANNED = [
    (r"\$\s*\d", "precio con símbolo $"),
    (r"compr(a|á)(lo|la|los|las| ahora| ya)\b", "imperativo de compra"),
    (r"\bcompra ahora\b", "imperativo de compra"),
    (r"contrat(a|á)(lo|nos| ahora| nuestro)", "imperativo de contratación"),
    (r"\boferta\b", "oferta de venta"),
    (r"descuento", "descuento"),
    (r"checkout", "checkout"),
    (r"(link|enlace) de pago", "enlace de pago"),
    (r"c[oó]digo (de )?(descuento|promocional)", "código promocional"),
    (r"solo hoy|[uú]ltimas plazas|por tiempo limitado", "urgencia de venta"),
    (r"rendimiento(s)? garantizado", "promesa de rendimiento"),
    (r"hazte rico|ganar[aá]s (dinero|miles)|sin riesgo", "promesa prohibida"),
    (r"precio(s)?\s*[:=]\s*\$", "precio con símbolo"),
]

def probe(path: Path) -> dict:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,width,height", "-show_entries", "format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True)
    return json.loads(p.stdout or "{}")

def volumes(path: Path) -> tuple[float, float]:
    p = subprocess.run(["ffmpeg", "-i", str(path), "-af", "volumedetect", "-vn", "-sn", "-dn",
                        "-f", "null", "/dev/null"], capture_output=True, text=True)
    mean = re.search(r"mean_volume:\s*(-?[\d.]+) dB", p.stderr)
    mx = re.search(r"max_volume:\s*(-?[\d.]+) dB", p.stderr)
    return (float(mean.group(1)) if mean else -99.0, float(mx.group(1)) if mx else -99.0)

def scan_banned(text: str) -> list[str]:
    low = f" {text.lower()} "
    return [label for pat, label in BANNED if re.search(pat, low)]

# --- MARCO DE ALCANCE (content/marco-alcance.md): checks de audiencia nueva ---
HOOK_FORBIDDEN = ("hola", "bienvenidos", "bienvenidas", "en este video", "en este vídeo",
                  "hoy vamos a", "qué tal", "como están", "como estan", "mi nombre es")
HOOK_NUMBER_RE = re.compile(r"\d|\b(una?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|"
                            r"veint\w+|treinta\w*|cuarenta\w*|cincuenta\w*|cien\w*|mil|mill[oó]n\w*|"
                            r"primer\w*|segund\w*|tercer\w*)\b")
HOOK_PROMISES = ("te doy", "te muestro", "te enseño", "te enseno", "gratis", "con números",
                 "con numeros", "paso a paso", "costando dinero", "te cuesta", "te puede costar",
                 "sin pagar", "descubre", "aprende a", "evita pagar")
# Jerga del nicho (ETAPA 4): patrón del término -> patrones que cuentan como
# explicación simple dentro de la misma pieza. ASSUMED_TERMS: términos que el
# canal ya asume explicados en piezas anteriores (vacío hoy a propósito:
# cada pieza debe funcionar para un desconocido, sin contexto previo).
ASSUMED_TERMS: set[str] = set()
JARGON = {
    "apr": (r"\bapr\b", [r"interés anual", r"tasa de interés", r"apr\s+es", r"es el interés"]),
    "llc": (r"\bllc\b", [r"responsabilidad limitada", r"llc\s+es", r"compañ[ií]a registrada"]),
    "ein": (r"\bein\b", [r"número de identificación", r"numero de identificacion",
                         r"número fiscal", r"numero fiscal", r"ein\s+es"]),
    "ira": (r"\bira\b", [r"jubilación", r"jubilacion", r"cuenta de retiro", r"ira\s+es"]),
    "tramo": (r"\btramos?\b", [r"tramos? de impuestos", r"rango de ingreso",
                               r"escala de ingreso", r"tramos?\s+(son|es)\b"]),
    "prima": (r"\bprimas?\b", [r"prima\s+es", r"lo que pagas", r"pago mensual",
                               r"cuota mensual", r"prima de (la )?parte b de medicare"]),
}
SIGNAL_TRIGGERS = {  # mismo criterio que tools/script_generator.py
    "guardados": ("guárdalo", "guardalo", "guarda este video", "guarda esta"),
    "compartidos": ("comparte", "compártelo", "compartelo", "envíaselo", "enviaselo", "pásalo", "pasalo"),
    "comentarios": ("comenta",),
    "suscripcion": ("sigue el canal", "suscríbete", "suscribete", "síguenos", "siguenos"),
}

def _first_sentence(text: str) -> str:
    m = re.split(r"(?<=[.?!])\s+", (text or "").strip(), maxsplit=1)
    return m[0] if m else (text or "")[:140]

def _stem_words(text: str) -> set[str]:
    stop = {"para", "como", "este", "esta", "esto", "tiene", "puede", "desde", "sobre",
            "cuando", "porque", "canal", "sigue", "comenta", "video"}
    out = set()
    for w in re.findall(r"[a-záéíóúñ]{4,}", (text or "").lower()):
        if w not in stop:
            out.add(w[:6] if len(w) >= 7 else w)  # tallo simple: herramienta~herramientas
    return out

def marco_checks(script: dict) -> dict:
    """Los 4 checks del marco de alcance sobre un guión. Devuelve
    {nombre: (ok, detalle)}. Pensado también para la prueba de humo."""
    res = {}
    if not script:
        return {n: (False, "sin guión") for n in
                ("hook_sin_contexto", "jerga_explicada", "senal_objetivo", "cierre_loop")}
    text = script.get("full_text", "") or ""
    low = text.lower()
    sections = script.get("sections", {}) or {}
    hook = sections.get("hook_0_3s") or _first_sentence(text)
    closing = sections.get("cierre_cta") or (text.rsplit(". ", 1)[-1] if text else "")
    # 1) HOOK SIN CONTEXTO: primeras ~10 palabras con pregunta/número/promesa
    #    y ninguna palabra de saludo/contexto en la primera frase.
    h_low = hook.lower()
    forb = [f for f in HOOK_FORBIDDEN if f in h_low]
    head = " ".join(h_low.split()[:10])
    has_q = "¿" in head or "?" in head
    has_n = bool(HOOK_NUMBER_RE.search(head))
    prom = [p for p in HOOK_PROMISES if p in head]
    ok_hook = not forb and (has_q or has_n or bool(prom))
    det = (f"prohibido: {forb}" if forb else
           ("pregunta en 0-2 s" if has_q else "número en 0-2 s" if has_n else
            f"promesa concreta: «{prom[0]}»" if prom else
            "sin pregunta, número ni promesa en las primeras ~10 palabras"))
    res["hook_sin_contexto"] = (ok_hook, f"hook: «{hook[:70]}…» — {det}")
    # 2) JERGA EXPLICADA: término presente sin explicación simple = falla.
    sin_expl = []
    for term, (pat, expls) in JARGON.items():
        if term in ASSUMED_TERMS:
            continue
        if re.search(pat, low) and not any(re.search(e, low) for e in expls):
            sin_expl.append(term.upper())
    res["jerga_explicada"] = (not sin_expl,
                               f"jerga sin explicar: {', '.join(sin_expl)}" if sin_expl
                               else "toda la jerga del nicho va explicada en lenguaje simple (o no se usa)")
    # 3) SEÑAL OBJETIVO: declarada en el guión y con disparador en el texto
    #    (comentarios simples: el disparador vive en el cierre).
    senal = script.get("senal_objetivo") or (script.get("estructura_alcance") or {}).get("senal_objetivo")
    if senal not in SIGNAL_TRIGGERS:
        res["senal_objetivo"] = (False, f"señal no declarada o inválida: {senal!r} "
                                        "(una de: guardados/compartidos/comentarios/suscripcion)")
    else:
        scope = closing if senal == "comentarios" else text
        trig = [t for t in SIGNAL_TRIGGERS[senal] if t in scope.lower()]
        res["senal_objetivo"] = (bool(trig),
                                 f"señal «{senal}» con disparador «{trig[0]}»" if trig
                                 else f"señal «{senal}» declarada pero SIN disparador en el guión")
    # 4) CIERRE EN LOOP: la última frase devuelve la promesa/pregunta del hook.
    if "¿" in closing or "?" in closing:
        res["cierre_loop"] = (True, "el cierre devuelve una pregunta: el inicio vuelve a tener sentido (replay)")
    else:
        overlap = _stem_words(hook) & _stem_words(closing)
        res["cierre_loop"] = (len(overlap) >= 2,
                              f"el cierre retoma el hook ({', '.join(sorted(overlap)[:3])})" if len(overlap) >= 2
                              else "el cierre NO conecta con la promesa del hook: se pierde el replay")
    return res

def check(pkg: Path) -> dict:
    checks, failures = {}, []
    def do(name, ok, detail=""):
        checks[name] = {"ok": bool(ok), "detail": detail}
        if not ok: failures.append(f"{name}: {detail}")
    mp4 = pkg / "short.mp4"
    do("video_existe", mp4.exists(), str(mp4))
    dur, w, h, has_audio = 0.0, 0, 0, False
    if mp4.exists():
        info = probe(mp4)
        dur = float((info.get("format") or {}).get("duration") or 0)
        for s in info.get("streams", []):
            if s.get("codec_type") == "video": w, h = s.get("width", 0), s.get("height", 0)
            if s.get("codec_type") == "audio": has_audio = True
    do("resolucion_1080x1920", (w, h) == (1080, 1920), f"{w}x{h}")
    do("duracion_20_95s", 20 <= dur <= 95, f"{dur:.1f} s")
    do("audio_presente", has_audio, "stream de audio")
    mean, mx = volumes(mp4) if mp4.exists() else (-99.0, -99.0)
    do("audio_no_silencio", mean > -45 and mx > -20, f"mean {mean} dB, max {mx} dB")
    srt = pkg / "captions.srt"
    blocks = len(re.findall(r"\d{2}:\d{2}:\d{2},\d{3} -->", srt.read_text(encoding="utf-8"))) if srt.exists() else 0
    do("subtitulos", blocks >= 5, f"{blocks} bloques")
    is_clip = not (pkg / "metadata.json").exists() and (pkg / "metadata_youtube.json").exists()
    meta = load_json(pkg / "metadata.json", {}) or (load_json(pkg / "metadata_youtube.json", {}) if is_clip else {})
    title = meta.get("title", ""); desc = meta.get("description", "")
    do("titulo_le_100", 0 < len(title) <= 100, f"{len(title)} caracteres")
    do("disclaimer", "asesoría" in desc or "asesoria" in desc, "disclaimer en descripción")
    man = load_json(pkg / "package_manifest.json", {})
    script = load_json(man.get("script", ""), {}) if man.get("script") else {}
    script_text = script.get("full_text", "")
    hits = sorted(set(scan_banned(script_text) + scan_banned(desc)))
    do("sin_venta_directa", not hits, f"hallazgos: {hits}" if hits else "limpio")
    ret = retention_optimizer.score_script(script) if script else {"score": 0, "motivos": ["sin guión"]}
    do("retencion_score_ge_70", ret["score"] >= 70, f"score {ret['score']}: {'; '.join(ret['motivos'])}")
    # Marco de alcance (content/marco-alcance.md): hook sin contexto, jerga
    # explicada, señal objetivo con disparador y cierre en loop.
    for _name, (_ok, _det) in marco_checks(script).items():
        do(_name, _ok, _det)
    # Layout por zonas: ningún texto fuera de su zona ni cortado por el borde.
    lfails = layout_mod.validate_layout(script) if script else ["sin guión"]
    do("layout_zonas_sin_solapes", not lfails, "; ".join(lfails) if lfails else "kicker/dato/apoyo/subtítulos medidos con PIL, zonas separadas")
    # Formato «foto real»: fotos reales con procedencia registrada o rechazo.
    script_format = (script.get("format") if script else None) or ""
    if script_format in ("foto_real", "imagen_generada"):  # imagen_generada = alias histórico
        rfails = layout_mod.validate_real_images(script)
        aman = load_json(pkg / "animated_manifest.json", {})
        if aman.get("format") != "foto_real":
            rfails.append("animated_manifest.json no declara format=foto_real "
                          "(¿render con un assembler viejo de iconos o de imágenes generadas?)")
        else:
            for u in aman.get("images", []):
                f = (layout_mod.real_dir(script) / u.get("file", ""))
                if not f.exists():
                    rfails.append(f"foto usada en el render no existe: {u.get('file')}")
                if not u.get("source") or not str(u.get("source_url", "")).startswith("http") or not u.get("license"):
                    rfails.append(f"foto usada en el render sin procedencia registrada: {u.get('file')}")
            if not aman.get("images"):
                rfails.append("animated_manifest.json sin lista de fotos usadas")
        do("fotos_reales_registradas", not rfails,
           "; ".join(rfails) if rfails else "manifiesto de fotos reales con procedencia y licencia + 1 foto por escena, registradas en el render")
        do("metraje_real_registrado", True, "paquete legado foto_real: no aplica (estándar vigente = metraje_real)")
        do("tarjeta_cierre", True, "paquete legado foto_real: no aplica")
        do("voz_ritmo_1_20", True, "paquete legado foto_real: no aplica")
        do("musica_libre_registrada", True, "paquete legado foto_real: no aplica")
    elif script_format == "metraje_real":
        # ESTÁNDAR VIGENTE (MANDATO §3d): metraje real + voz 1.20× + cierre.
        do("fotos_reales_registradas", True, "formato metraje_real: el check de fotos no aplica (ver metraje_real_registrado)")
        vfails = layout_mod.validate_footage(script)
        fman = load_json(pkg / "footage_manifest.json", {})
        card_sec = 0.0
        if fman.get("format") != "metraje_real":
            vfails.append("footage_manifest.json no declara format=metraje_real "
                          "(¿render con un assembler que no es el del estándar vigente?)")
        else:
            fdir = layout_mod.footage_dir(script)
            for u in fman.get("clips", []):
                f = fdir / u.get("file", "")
                if not f.exists():
                    vfails.append(f"clip usado en el render no existe: {u.get('file')}")
                if not u.get("source") or not str(u.get("source_url", "")).startswith("http") or not u.get("license"):
                    vfails.append(f"clip usado en el render sin procedencia registrada: {u.get('file')}")
            if not fman.get("clips"):
                vfails.append("footage_manifest.json sin lista de clips usados")
            segs = fman.get("segments", [])
            if len(segs) < 8:
                vfails.append(f"edición con {len(segs)} cortes (<8): el listón pide cortes cada 4-6 s")
            elif segs:
                durs = [float(s.get("dur") or 0) for s in segs]
                avg = sum(durs) / len(durs)
                if not (3.8 <= avg <= 6.5):
                    vfails.append(f"corte promedio de {avg:.2f} s (fuera de 3.8-6.5): listón = cortes cada 4-6 s, edición fluida y respirable")
                cortos = [(i + 1, d) for i, d in enumerate(durs) if i > 0 and d < 3.0]
                if cortos:
                    vfails.append("cortes bajo el mínimo de 3 s (solo el gancho inicial puede bajar): "
                                  + ", ".join(f"#{i}={d:.2f} s" for i, d in cortos))
            card_sec = float((fman.get("closing_card") or {}).get("seconds") or 0)
        do("metraje_real_registrado", not vfails,
           "; ".join(vfails) if vfails else "manifiesto de metraje real con procedencia por clip + edición de cortes 4-6 s registrada")
        # Tarjeta de cierre con el emblema vigente.
        cc = fman.get("closing_card", {}) if fman else {}
        do("tarjeta_cierre", cc.get("present") is True and 2.0 <= card_sec <= 3.5
           and "avatar-v2" in str(cc.get("emblem", "")),
           f"presente={cc.get('present')}, {card_sec:.1f} s, emblema={cc.get('emblem', 'FALTA')}")
        # Voz a 1.20× EFECTIVO: length_scale == config y duración consistente.
        # Base medida de la voz es_MX-claude-high a 1.0×: 167 palabras/min
        # (guión de la Fed: 178 palabras -> 63.81 s, 2026-10-20).
        import yaml as _yaml
        _cfg = _yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
        _ls_cfg = float(((_cfg.get("tts") or {}).get("piper_length_scale")) or 0)
        ttsm = load_json(pkg / "tts_manifest.json", {})
        ls = ttsm.get("length_scale")
        words = len(script_text.split())
        voice_dur = dur - card_sec
        exp_dur = words / 167.0 * 60 / 1.20 if words else 0.0
        ok_rate = (ls is not None and _ls_cfg > 0 and abs(float(ls) - _ls_cfg) <= 0.01
                   and exp_dur > 0 and abs(voice_dur - exp_dur) <= max(3.5, exp_dur * 0.12))
        do("voz_ritmo_1_20", ok_rate,
           f"length_scale={ls} (config {_ls_cfg}), voz {voice_dur:.1f} s vs {exp_dur:.1f} s esperados a 1.20× efectivo")
        # Cama musical: solo registrada con licencia clara, o ausente declarada.
        mus = fman.get("music") if fman else None
        do("musica_libre_registrada", mus is None or (bool(mus.get("license")) and bool(mus.get("source"))
           and str(mus.get("source_url", "")).startswith("http")),
           "sin cama musical (declarado)" if mus is None else
           f"{mus.get('title', '?')} — {mus.get('license', 'SIN LICENCIA')} ({mus.get('source', '?')})")
    else:
        do("fotos_reales_registradas", True, "formato sin foto real: no aplica")
        do("metraje_real_registrado", True, "formato sin metraje real: no aplica")
        do("tarjeta_cierre", True, "formato sin tarjeta de cierre del estándar: no aplica")
        do("voz_ritmo_1_20", True, "check de ritmo ligado al estándar metraje_real: no aplica")
        do("musica_libre_registrada", True, "formato sin cama musical del estándar: no aplica")
    # Fuentes en la descripción (solo piezas de actualidad).
    news = (script.get("news") if script else None) or meta.get("news") or {}
    if news:
        url = news.get("source_url", "")
        ok_url = isinstance(url, str) and url.startswith("http")
        do("fuentes_en_descripcion", ok_url and "Fuentes:" in desc and url in desc,
           f"fuente={news.get('fuente', '')[:60]} url={url or 'FALTA'} bloque={'sí' if 'Fuentes:' in desc else 'NO'}")
    else:
        do("fuentes_en_descripcion", True, "pieza sin noticia (evergreen): no aplica")
    # Paquetes espejo: puertas extra de TikTok sobre el mismo MP4 maestro.
    if is_clip:
        tt = load_json(pkg / "metadata_tiktok.json", {})
        do("tiktok_metadata", bool(tt), "metadata_tiktok.json presente")
        if tt:
            do("tiktok_ai_disclosure", tt.get("ai_disclosure") is True and bool(tt.get("ai_disclosure_label")),
               "ai_disclosure=true + etiqueta (voz sintética Piper; TikTok lo exige)")
            cap = tt.get("caption", "")
            do("tiktok_caption", 0 < len(cap) <= 2200 and len(tt.get("hashtags", [])) >= 3,
               f"{len(cap)} caracteres, {len(tt.get('hashtags', []))} hashtags")
            tt_hits = sorted(set(scan_banned(cap)))
            do("tiktok_sin_venta", not tt_hits, f"hallazgos: {tt_hits}" if tt_hits else "limpio")
        do("espejo_fuente_propia", bool(man.get("source")),
           "manifiesto con fuente espejo registrada (solo contenido nuestro)")
    # QC visual: sin capturas no hay ready (la falla original fue no mirar).
    fdir = pkg / "frames"
    nframes = len(list(fdir.glob("frame-*.png"))) if fdir.exists() else 0
    do("frames_qc_visual", nframes >= 3 and (fdir / "contacto.png").exists(),
       f"{nframes} cuadros + {'contacto.png' if (fdir / 'contacto.png').exists() else 'SIN hoja de contacto'}")
    publish_ready = not failures and "[RECURSO-GRATIS-" not in desc and "[ECOSISTEMA-" not in desc
    result = {"package": str(pkg), "passed": not failures, "publish_ready": publish_ready,
              "checks": checks, "failures": failures, "retention": ret,
              "publish_note": "listo para publicar (si hay canal+token y auto_publish)"
                              if publish_ready else
                              "en ready/ pero NO publicable aún: placeholders de recursos gratis sin resolver o QC fallido"}
    (pkg / "qc.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--package", required=True)
    args = ap.parse_args()
    print(json.dumps(check(Path(args.package)), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
