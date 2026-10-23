#!/usr/bin/env python3
"""
script_generator.py — Guión de Short de 45-60 s en ESPAÑOL PURO (sin spanglish visible).

Canal: Your Channel — finanzas personales/negocios + IA para hispanos en USA.
Educación general: SIN consejo financiero personalizado, SIN promesas de rendimientos.
Los guiones de temas de dinero/crédito/impuestos cierran con disclaimer breve.

Estructura obligatoria:
  hook    (0-3 s)   : pregunta o error que detiene el scroll
  desarrollo        : 3 bloques cortos, explicación ORIGINAL con ejemplo propio
  cierre + CTA      : conclusión + "Sigue el canal / comenta" en español (CTA suave)

MARCO DE ALCANCE (content/marco-alcance.md, doctrina desde 2026-10-20):
  - HOOK SIN CONTEXTO (0-2 s): funciona para quien NUNCA vio el canal;
    pregunta, número o promesa específica y observable; PROHIBIDO saludar,
    presentarse o «en este video…»; jerga del nicho (APR, LLC, EIN, IRA,
    tramo, prima) explicada en lenguaje simple dentro de la misma pieza.
  - ANTI-LINEAL: micro-curiosidad o dato nuevo cada ~12-15 s (cada bloque
    abre una idea nueva); sin pausas muertas. El contenido lineal muere.
  - CIERRE EN LOOP: la última frase devuelve la promesa/pregunta del hook
    para que el replay del Short sea natural.
  - SEÑAL OBJETIVO (una sola por pieza, campo «senal_objetivo»): la pieza
    declara qué señal busca (guardados / compartidos / comentarios /
    suscripcion) y el guión lleva su DISPARADOR audible (ver SENAL_TRIGGERS).
    El QC (automation/qc.py) verifica hook, jerga, señal y loop.

Modos:
  1) Guiones a medida (CUSTOM_SCRIPTS): los 3 temas de la primera tanda están
     escritos a mano y se devuelven exactos.
  2) LLM: si existe la variable de entorno de config.yaml (HERMES_API_URL),
     intenta POST estilo OpenAI /chat/completions con las reglas del canal.
  3) Offline (fallback): plantillas por tipo de tema (credito / llc-impuestos /
     ahorro-cuentas / ia-negocios / ia-tecnologia / inversion / hipotecas /
     negocios / vida-practica / errores / historias).
  Cada guión lleva su «categoria_mezcla» (MANDATO §1d) y --from-queue elige
  el siguiente tema por ROTACIÓN POR DÉFICIT de categoría, no por orden FIFO.

Uso:
    python3 tools/script_generator.py --topic "Tu puntaje de crédito explicado en 60 segundos: los 5 factores"
Salida: content/scripts/<slug>.json + <slug>.txt y JSON por stdout.
"""
import argparse, json, os, sys, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import (CONTENT, load_json, save_json, slugify, load_config,
                    estimate_seconds, mix_category, mix_pcts, mix_deficits)

DISCLAIMER = "Esto es educación general, no asesoría financiera personalizada."

# --- Guiones a medida de la primera tanda (escritos a mano, ver content/guiones-finanzas/) ---
CUSTOM_SCRIPTS = {
    "El error con tu tarjeta que te cuesta cientos en USA": {
        "hook": "¿Pagas solo el mínimo de tu tarjeta? Ese es el error que te puede costar cientos de dólares en Estados Unidos.",
        "blocks": [
            "Te lo muestro con números simples. Si debes mil dólares con un interés anual cercano al veinticuatro por ciento, y pagas solo el mínimo, gran parte de tu pago se va en intereses y la deuda baja muy despacio. Durante meses estarías pagando por lo mismo, una y otra vez.",
            "Ahora mira la diferencia: si pagas una cantidad fija mayor cada mes, por ejemplo cien dólares, atacas el capital desde el principio y la deuda se acorta muchísimo. No necesitas pagar todo de golpe: necesitas pagar más que el mínimo, siempre el mismo día, sin fallar.",
            "Consejo práctico: revisa tu estado de cuenta hoy y programa un pago fijo por encima del mínimo.",
        ],
        "closing": "Esto es educación general, no asesoría financiera. Sigue el canal y comenta: ¿pagas el mínimo o pagas más?",
        "on_screen": ["EL ERROR DEL PAGO MÍNIMO", "DEUDA $1.000 — EJEMPLO", "PAGA FIJO, NO EL MÍNIMO"],
        "kind": "credito",
    },
    "LLC o trabajar con tu nombre: la diferencia en impuestos explicada en 60 segundos": {
        "hook": "¿Trabajas con tu nombre o con una LLC? Esa decisión cambia cómo ordenas tu dinero y cómo pagas impuestos.",
        "blocks": [
            "Primero, qué es: una LLC es una compañía de responsabilidad limitada registrada en tu estado; separa, en papel y en cuenta bancaria, al negocio de tu bolsillo personal.",
            "Si trabajas con tu nombre, negocio y persona son lo mismo: cobras tú, declaras tú, y mezclar gastos se vuelve un dolor de cabeza.",
            "Y atención al mito: tener la compañía no significa pagar cero impuestos; la ganancia suele llegar a tu declaración personal, salvo otra elección hecha con un profesional. La ventaja real es orden, separación y una base seria para crecer. Antes de registrar, compara tu caso con un contador.",
        ],
        "closing": "Esto es educación general, no asesoría fiscal. Comenta tu estado y sigue el canal.",
        "on_screen": ["¿TU NOMBRE O LLC?", "SEPARA EL DINERO", "NO ES CERO IMPUESTOS"],
        "kind": "llc-impuestos",
    },
    "3 herramientas de IA gratis que un negocio pequeño puede usar hoy": {
        "hook": "Tu negocio pequeño puede usar inteligencia artificial gratis desde hoy, sin contratar a nadie. Te doy tres herramientas y un uso concreto para cada una.",
        "blocks": [
            "Primera: un asistente de conversación para redactar respuestas a clientes, presupuestos y mensajes de seguimiento en minutos, siempre revisando antes de enviar.",
            "Segunda: un diseñador con plantillas para crear tus publicaciones, volantes y el menú de precios de la semana sin pagar diseñador.",
            "Tercera: un generador de subtítulos automáticos para tus videos, porque la mayoría de la gente mira el celular sin sonido. La regla de oro: la máquina propone y tú apruebas; nunca publiques precios ni promesas sin revisarlos.",
        ],
        "closing": "Elige una sola herramienta hoy y pruébala con una tarea real de tu negocio. Comenta qué tipo de negocio tienes y te digo cuál probar primero. Sigue el canal para una idea cada día.",
        "on_screen": ["3 IA GRATIS HOY", "1 TEXTOS · 2 DISEÑO · 3 SUBTÍTULOS", "LA MÁQUINA PROPONE, TÚ APRUEBAS"],
        "kind": "ia-negocios",
    },
}

# --- Tanda de ACTUALIDAD verificada (semana del 14-oct-2026) ---
CUSTOM_SCRIPTS.update({
    "Seguro Social sube 3.6% en 2027: cuánto más llega en enero": {
        "hook": "¿Tú o tus padres reciben Seguro Social? El catorce de octubre se anunció el aumento de dos mil veintisiete: tres punto seis por ciento.",
        "blocks": [
            "Qué significa en dinero: el beneficio promedio del jubilado sube unos setenta y cinco dólares al mes desde enero, cerca de novecientos dólares en el año. Son promedios: tu aumento es el tres punto seis por ciento de tu propio cheque.",
            "Por qué sube: el ajuste sigue la inflación oficial de julio a septiembre, y el dato de septiembre marcó tres punto siete por ciento. Es el aumento mayor desde el de dos mil veintitrés.",
            "Por eso, qué revisar: a finales de noviembre llega el aviso oficial con tu monto exacto a tu cuenta en línea. Y atención: la prima de la parte B de Medicare puede comerse una parte del aumento cuando se anuncie.",
        ],
        "closing": "Esto es educación general, no asesoría financiera. Sigue el canal: cada día, la noticia de dinero que sí te afecta. ¿Ya calculaste tu tres punto seis por ciento?",
        "on_screen": ["SEGURO SOCIAL +3.6% EN 2027", "PROMEDIO: +75 AL MES", "REVISA TU AVISO EN NOVIEMBRE"],
        "kind": "actualidad",
        "kicker": "DINERO EN USA · SEGURO SOCIAL",
        "scenes_visual": [
            {"big": "+3,6%", "support": "sube el Seguro Social en 2027", "icon": "edificio"},
            {"big": "+$75", "support": "más al mes en promedio, desde enero", "icon": "calendario"},
            {"big": "3,7%", "support": "la inflación de septiembre empuja el ajuste", "icon": "grafica"},
            {"big": "FIN DE NOV", "support": "llega tu aviso oficial con el monto exacto", "icon": "documento"},
            {"big": "CADA DÍA", "support": "la noticia de dinero que sí te afecta", "icon": "moneda"},
        ],
        "news": {"fuente": "Administración del Seguro Social (SSA), comunicado del 14 de octubre de 2026",
                 "source_url": "https://www.ssa.gov/news/en/press/releases/2026-10-14.html",
                 "fecha_noticia": "2026-10-14",
                 "sources": [{"name": "Administración del Seguro Social (SSA) — «Social Security Announces 3.6 Percent Benefit Increase for 2027»",
                              "url": "https://www.ssa.gov/news/en/press/releases/2026-10-14.html", "date": "2026-10-14"}]},
    },
    "La Fed decide el 28 de octubre: tu tarjeta y tu ahorro esta semana": {
        "hook": "El veintiocho de octubre la Reserva Federal decide las tasas otra vez. ¿Y eso qué tiene que ver con tu bolsillo? Todo.",
        "blocks": [
            "El contexto: en septiembre la Fed subió su tasa a entre tres punto setenta y cinco y cuatro por ciento, la primera subida desde dos mil veintitrés, con la inflación de septiembre en tres punto siete por ciento.",
            "Tu tarjeta: casi todas tienen tasa variable, y el interés promedio de las ofertas nuevas ronda el veinticuatro por ciento anual. Si la Fed sube otra vez, tu próximo estado de cuenta puede salir más caro: pagar más que el mínimo esta semana sí mueve la aguja.",
            "Tu ahorro: las cuentas de alto rendimiento pagan cerca de cuatro punto veintisiete por ciento anual, contra casi nada en la banca tradicional. Mover tu fondo de emergencia a una cuenta que sí pague es la jugada tranquila de la semana.",
        ],
        "closing": "Esto es educación general, no asesoría financiera. Comenta si vas a revisar tu tarjeta o tu ahorro primero, y sigue el canal para el resultado explicado fácil el mismo veintiocho.",
        "on_screen": ["LA FED DECIDE EL 28 DE OCTUBRE", "TARJETAS: CERCA DEL 24% ANUAL", "AHORRO QUE SÍ PAGA: 4.27%"],
        "kind": "actualidad",
        "kicker": "DINERO EN USA · LA FED",
        "scenes_visual": [
            {"big": "28 OCT", "support": "la Reserva Federal decide las tasas", "icon": "edificio"},
            {"big": "3,75–4%", "support": "la tasa tras la subida de septiembre", "icon": "grafica"},
            {"big": "24%", "support": "interés anual típico de las tarjetas", "icon": "tarjeta"},
            {"big": "4,27%", "support": "eso pagan las cuentas de ahorro que sí rinden", "icon": "moneda"},
            {"big": "EL 28", "support": "te explicamos el resultado el mismo día", "icon": "calendario"},
        ],
        "news": {"fuente": "Reserva Federal (FOMC, reunión del 27-28 de octubre de 2026) y datos de inflación BLS del 14-oct-2026",
                 "source_url": "https://www.newstod.com/article/fed-decision-wednesday-october-28-200-pm-et-statement-230-press-conference",
                 "fecha_noticia": "2026-10-14",
                 "sources": [{"name": "Reserva Federal (FOMC) — decisión del 28 de octubre de 2026, 2:00 p. m. ET, y subida previa del 16-sep-2026 a 3,75%-4,00%",
                              "url": "https://www.newstod.com/article/fed-decision-wednesday-october-28-200-pm-et-statement-230-press-conference", "date": "2026-10-14"},
                             {"name": "CME FedWatch / datos de tasas de la Reserva Federal (expectativas al 18-oct-2026)",
                              "url": "https://growbeansprout.com/tools/fedwatch", "date": "2026-10-18"}]},
    },
    "El IRS aún no publica los tramos 2027: qué hacer mientras tanto": {
        "hook": "Ya es finales de octubre y el IRS todavía no publica los tramos de impuestos de dos mil veintisiete. ¿Por qué importa? Porque de esos números depende tu planificación.",
        "blocks": [
            "El dato: al catorce de octubre la agencia no había publicado ni los tramos ni la deducción estándar del próximo año, algo inusual: los dos años anteriores el anuncio llegó el nueve y el veintidós de octubre.",
            "Lo que se proyecta: firmas especializadas estiman un ajuste cercano a tres punto dos por ciento por inflación. Ojo: son proyecciones, no cifras oficiales, y nadie debería decidir con números inventados.",
            "Por eso, qué hacer mientras tanto: separa desde ya tu porcentaje para impuestos en una cuenta aparte y, cuando salga el anuncio oficial, ajustas todo con tu contador en una sola sesión.",
        ],
        "closing": "Esto es educación general, no asesoría fiscal. Cuando el IRS publique, lo explicamos aquí el mismo día: sigue el canal y comenta si declaras como empleado o con negocio propio.",
        "on_screen": ["IRS: TRAMOS 2027 SIN PUBLICAR", "PROYECCIÓN NO ES CIFRA OFICIAL", "SEPARA TU IMPUESTO DESDE YA"],
        "kind": "actualidad",
        "kicker": "DINERO EN USA · IRS",
        "scenes_visual": [
            {"big": "2027", "support": "el IRS aún no publica los tramos", "icon": "calendario"},
            {"big": "14 OCT", "support": "y seguía sin anuncio oficial", "icon": "documento"},
            {"big": "3,2%", "support": "ajuste proyectado: no es cifra oficial", "icon": "grafica"},
            {"big": "SEPARA", "support": "aparta tu impuesto en una cuenta aparte", "icon": "moneda"},
            {"big": "EL MISMO DÍA", "support": "lo explicamos aquí cuando se publique", "icon": "telefono"},
        ],
        "news": {"fuente": "The Money Overview, 14 de octubre de 2026; proyecciones Bloomberg Tax y Wolters Kluwer",
                 "source_url": "https://themoneyoverview.com/irs-still-had-not-posted-2027-tax-brackets-as-of-october-14/",
                 "fecha_noticia": "2026-10-14",
                 "sources": [{"name": "The Money Overview — «The IRS still had not posted 2027 tax brackets as of October 14»",
                              "url": "https://themoneyoverview.com/irs-still-had-not-posted-2027-tax-brackets-as-of-october-14/", "date": "2026-10-14"},
                             {"name": "Proyecciones 2027 de Wolters Kluwer / Bloomberg Tax (ajuste proyectado ~3,2%)",
                              "url": "https://jupid.com/blog/2027-tax-brackets", "date": "2026-09-18"}]},
    },
})

FACTS = {
    "credito": "Pagar a tiempo y usar una parte baja de tu límite son los dos factores que más pesan en tu puntaje de crédito. No hay trucos: hay hábitos repetidos mes tras mes.",
    "llc-impuestos": "La separación lo es todo: cuenta del negocio para el negocio, cuenta personal para tu vida. Con ese orden, los registros, las deducciones y los impuestos se vuelven manejables.",
    "ahorro-cuentas": "El ahorro que funciona es automático: se aparta el día de pago, antes de gastar, en una cuenta separada que no miras todos los días.",
    "ia-negocios": "La inteligencia artificial rinde cuando hace tareas concretas y repetidas: redactar, diseñar, subtitular. La estrategia y la revisión final siguen siendo humanas.",
    "ia-tecnologia": "La inteligencia artificial rinde cuando hace tareas concretas y repetidas: redactar, diseñar, subtitular. La estrategia y la revisión final siguen siendo humanas.",
    "inversion": "Invertir con orden no es adivinar el mercado: es automatizar un aporte constante, diversificar y dejar que el tiempo y el interés compuesto hagan su trabajo. Sin promesas: con disciplina.",
    "hipotecas": "Una hipoteca se decide con la cuenta completa: tasa, plazo, pago inicial y costo total en intereses. La mensualidad más baja no siempre es la casa más barata.",
    "negocios": "Un negocio crece cuando su dueño pasa de hacer todo a tener sistemas: precios con margen, cobros a tiempo y procesos que no dependen de su memoria.",
    "vida-practica": "Los gastos grandes de la vida en USA —salud, vivienda y jubilación— se deciden antes de la urgencia: comparar opciones y leer los costos reales ahorra miles.",
    "errores": "La mayoría de los problemas de dinero no vienen de un gasto gigante, sino de un hábito pequeño repetido sin darte cuenta durante meses.",
    "historias": "Los negocios que duran no son los que nunca fallan: son los que ordenan sus números temprano y aprenden de cada error sin esconderlo.",
    "default": "Ordenar tu dinero no requiere ganar más: requiere que cada dólar tenga un trabajo asignado antes de que empiece el mes.",
}
HOOKS = [
    # Marco de alcance, ETAPA 1: hook SIN CONTEXTO (0-2 s) — pregunta, número
    # o promesa concreta; sin saludos ni «en este video»; sentido completo
    # para quien nunca vio el canal. El QC (hook_sin_contexto) los verifica.
    "Esto te puede estar costando dinero sin que lo notes: {tema_min}.",
    "¿Vives y trabajas en Estados Unidos? Entonces esto te afecta directo: {tema_min}.",
    "En 60 segundos y con números reales: {tema_min}.",
]
CLOSINGS = [
    "Comenta tu caso sin datos personales, comparte este video con quien lo necesite y sigue el canal: dinero y negocio en USA, explicados fácil cada día.",
    "Déjame tu pregunta en los comentarios y sigue el canal para la guía completa en español.",
]

# --- SEÑAL OBJETIVO (marco de alcance, ETAPA 3): una por pieza, con disparador ---
# La pieza declara qué señal del algoritmo busca; el disparador debe ESCUCHARSE
# en el guión. El QC (senal_objetivo) verifica declaración + disparador.
SENAL_POR_KIND = {  # señal por defecto según el tipo de tema
    "credito": "guardados", "llc-impuestos": "guardados", "ahorro-cuentas": "guardados",
    "inversion": "guardados", "hipotecas": "guardados", "vida-practica": "guardados",
    "actualidad": "guardados",
    "ia-negocios": "compartidos", "ia-tecnologia": "compartidos", "negocios": "compartidos",
    "errores": "comentarios", "historias": "comentarios",
}
SENAL_TRIGGER_SENTENCE = {  # frase que se AÑADE al cierre de plantilla si falta el disparador
    "guardados": "Guárdalo para tenerlo a mano cuando lo necesites.",
    "compartidos": "Compártelo con alguien a quien le sirva esta semana.",
    "comentarios": "Comenta SÍ o NO: ¿te pasa esto a ti?",
    "suscripcion": "Sigue el canal: cada día un tema de dinero, IA o negocios, explicado fácil.",
}
SENAL_TRIGGERS = {  # cómo se reconoce el disparador en el texto (mismo criterio que el QC)
    "guardados": ("guárdalo", "guardalo", "guarda este video", "guarda esta"),
    "compartidos": ("comparte", "compártelo", "compartelo", "envíaselo", "enviaselo", "pásalo", "pasalo"),
    "comentarios": ("comenta",),
    "suscripcion": ("sigue el canal", "suscríbete", "suscribete", "síguenos", "siguenos"),
}

def senal_disparador_presente(senal: str, closing: str, full: str) -> bool:
    """¿El guión lleva el disparador de la señal? (comentarios se busca en el cierre)."""
    scope = closing if senal == "comentarios" else full
    return any(t in scope.lower() for t in SENAL_TRIGGERS.get(senal, ()))

def derive_senal(closing: str, full: str = "") -> str | None:
    """Señal que el cierre YA dispara (para guiones a medida: se etiqueta, no se reescribe)."""
    low_c = (closing or "").lower()
    if "comenta" in low_c and ("¿" in closing or "?" in closing):
        return "comentarios"
    for s in ("compartidos", "guardados", "suscripcion"):
        if senal_disparador_presente(s, closing, full or closing):
            return s
    if "comenta" in low_c:
        return "comentarios"
    return None

def _build(topic, kind, mode, hook, blocks, closing, on_screen=None, news=None, kicker=None, scenes_visual=None,
           categoria=None, senal=None):
    full = " ".join([hook] + list(blocks) + [closing])
    words = len(full.split())
    senal = senal or derive_senal(closing, full) or "suscripcion"
    out = {"topic": topic, "kind": kind, "mode": mode,
           "senal_objetivo": senal,  # marco de alcance ETAPA 3 (declarada; el QC verifica su disparador)
           "estructura_alcance": {"hook_sin_contexto": True, "micro_curiosidad_cada_s": "12-15",
                                  "cierre_loop": True, "senal_objetivo": senal},
           "categoria_mezcla": mix_category(kind, categoria),  # mezcla editorial §1d
            "sections": {"hook_0_3s": hook, "desarrollo": list(blocks), "cierre_cta": closing},
            "full_text": full, "word_count": words,
            "estimated_seconds": estimate_seconds(words),
            "kicker": kicker or "DINERO EN USA · HOY",
            "on_screen_text": on_screen or [hook.split(".")[0] + ".", "Dinero inteligente en USA", "¿Te pasó? Comenta"],
            "visual_plan": ["Fondo gráfico propio del canal + texto grande animado",
                            "Tarjeta de datos o comparativa propia (sin imágenes de terceros)",
                            "Cierre con marca del canal y llamado a comentar y seguir"],
            "disclaimer": DISCLAIMER}
    if scenes_visual:
        out["scenes_visual"] = scenes_visual  # layout v2: dato grande + apoyo + icono por escena
    if news:
        out["news"] = news  # actualidad verificada: fuente + fecha + URL (QC exige fuente con URL)
        out["mode"] = mode + "+actualidad"
    return out

def template_script(topic: str, kind: str = "evergreen", angle: str = "") -> dict:
    if topic in CUSTOM_SCRIPTS:
        c = CUSTOM_SCRIPTS[topic]
        return _build(topic, c["kind"], "a-medida-primera-tanda", c["hook"], c["blocks"], c["closing"], c["on_screen"], c.get("news"),
                      c.get("kicker"), c.get("scenes_visual"))
    tema_min = topic[0].lower() + topic[1:] if topic else "esto"
    hook = HOOKS[abs(hash(topic)) % len(HOOKS)].format(tema_min=tema_min.rstrip("."))
    fact = FACTS.get(kind, FACTS["default"])
    if angle:
        fact = f"{angle} {fact}"
    blocks = [
        f"Primero, lo esencial. {fact}",
        "Segundo, el ejemplo que lo aclara: piensa en dos personas con el mismo ingreso. La que ordena primero y decide con números gasta menos en intereses, multas y errores, sin dejar de vivir su vida.",
        "Y tercero, la acción de hoy: elige un solo paso pequeño, hazlo esta semana y mide el resultado el próximo mes. El orden financiero se construye por capas, no de golpe.",
    ]
    closing = CLOSINGS[abs(hash(topic)) % len(CLOSINGS)]
    if kind in ("credito", "llc-impuestos", "ahorro-cuentas", "errores",
                "inversion", "hipotecas", "vida-practica"):
        closing = f"{DISCLAIMER} " + closing
    # Señal objetivo (marco ETAPA 3): la plantilla declara la señal de su tipo
    # y GARANTIZA su disparador en el cierre (se añade la frase si falta).
    senal = SENAL_POR_KIND.get(kind, "suscripcion")
    full_prev = " ".join([hook] + blocks + [closing])
    if not senal_disparador_presente(senal, closing, full_prev):
        closing = closing.rstrip() + " " + SENAL_TRIGGER_SENTENCE[senal]
    # Cierre en loop (marco ETAPA 2): si el cierre no devuelve ya una
    # pregunta, se cierra devolviendo la pregunta del tema al espectador —
    # el inicio vuelve a tener sentido y el replay es natural.
    if "¿" not in closing and "?" not in closing:
        closing = closing.rstrip() + f" Y la pregunta del inicio sigue en pie: ¿{tema_min.rstrip('.')}?"
    return _build(topic, kind, "plantillas-offline", hook, blocks, closing, senal=senal)

def _hermes_key(cfg: dict) -> str:
    k = os.environ.get("HERMES_API_KEY", "")
    if k:
        return k
    try:
        for line in open(os.path.expanduser("~/.config/YourChannel/secrets")):
            if line.startswith("LOCAL_LLM_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def _hermes_opener(url: str):
    """Optional outbound proxy for reaching your LAN model server from a
    sandboxed environment: set SHORTSFORGE_PROXY (e.g. http://user:pass@host:3128).
    Without it, requests go direct — the normal case on your own machine."""
    px = os.environ.get("SHORTSFORGE_PROXY", "")
    if px:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": px, "https": px}))
    return urllib.request.build_opener()


def llm_script(topic: str, kind: str, angle: str, cfg: dict) -> dict | None:
    if topic in CUSTOM_SCRIPTS:
        return None  # los de la primera tanda siempre van a medida
    llmcfg = cfg.get("llm") or {}
    url = os.environ.get(llmcfg.get("endpoint_env", "HERMES_API_URL"), "") or llmcfg.get("endpoint", "")
    if not url:
        return None
    api_key = _hermes_key(cfg)
    prompt = (f"Escribe SOLO el texto corrido de un guion de YouTube Short en español puro, "
              f"150 a 170 palabras exactas, para hispanos en USA, sobre el tema: «{topic}». "
              "REGLAS DURAS: nada de título, nada de markdown, nada de marcas de tiempo, nada de emojis, "
              "nada de indicaciones de escena: únicamente las frases que dice la voz. "
              "La primera frase es un gancho en forma de pregunta o cifra concreta que funcione SIN contexto "
              "para quien nunca vio el canal. Incluye un ejemplo con números sencillos y propios. Explica en "
              "palabras simples cualquier término del nicho (APR, LLC, EIN, IRA, tramo, prima). Mete una "
              "micro-curiosidad o dato nuevo cada 12-15 segundos. Cierra devolviendo la pregunta del gancho "
              "e invitando a guardar el video o seguir el canal. Educación general: nada de consejo "
              "financiero personalizado ni promesas de rendimiento.")
    payload = {"model": os.environ.get("HERMES_MODEL", "") or llmcfg.get("model", "hermes-auto"),
               "messages": [{"role": "user", "content": prompt}], "temperature": 0.7}
    try:
        hdrs = {"Content-Type": "application/json"}
        if api_key:
            hdrs["Authorization"] = "Bearer " + api_key
        req = urllib.request.Request(url.rstrip("/") + "/chat/completions",
                                     data=json.dumps(payload).encode(),
                                     headers=hdrs)
        with _hermes_opener(url).open(req, timeout=int(llmcfg.get("timeout_sec", 180))) as r:
            text = json.loads(r.read())["choices"][0]["message"]["content"].strip()
        words = len(text.split())
        if not (140 <= words <= 185):
            payload2 = dict(payload)
            payload2["messages"] = [{"role": "user", "content": prompt +
                f" NOTA: tu intento anterior tuvo {words} palabras; reescribe en 150-170 exactas."}]
            try:
                req2 = urllib.request.Request(url.rstrip("/") + "/chat/completions",
                                              data=json.dumps(payload2).encode(), headers=hdrs)
                with _hermes_opener(url).open(req2, timeout=int(llmcfg.get("timeout_sec", 180))) as r2:
                    text2 = json.loads(r2.read())["choices"][0]["message"]["content"].strip()
                if 130 <= len(text2.split()) <= 195:
                    text, words = text2, len(text2.split())
            except Exception:
                pass
        if words > 195:
            # Ni el original ni el reintento respetaron el largo de un Short:
            # se descarta y generate() cae a plantillas (la puerta QC manda).
            print(f"[script_generator] Hermes fuera de largo ({words} palabras); uso plantillas.", file=sys.stderr)
            return None
        closing_llm = text.rsplit(". ", 1)[-1] if ". " in text else ""
        senal_llm = derive_senal(closing_llm, text) or SENAL_POR_KIND.get(kind, "suscripcion")
        return {"topic": topic, "kind": kind, "mode": "llm-hermes", "full_text": text,
                "senal_objetivo": senal_llm,
                "estructura_alcance": {"hook_sin_contexto": True, "micro_curiosidad_cada_s": "12-15",
                                       "cierre_loop": True, "senal_objetivo": senal_llm},
                "sections": {"hook_0_3s": text.split(".")[0] + ".", "desarrollo": [], "cierre_cta": ""},
                "word_count": words, "estimated_seconds": estimate_seconds(words),
                "on_screen_text": [], "visual_plan": [], "disclaimer": DISCLAIMER}
    except Exception as e:
        print(f"[script_generator] LLM falló ({e}); uso plantillas offline.", file=sys.stderr)
        return None

def generate(topic: str, kind: str = "evergreen", angle: str = "") -> dict:
    cfg = load_config()
    # Ruta principal (2026-10-22): ciclo escritor-juez con meta 100
    # (Hermes escribe, medidor + jev juzgan, reescribe con la crítica).
    try:
        import judge_loop
        s, score, _n = judge_loop.generate_judged(topic, kind, log=lambda *a: None)
        if s:
            return s
    except Exception as e:
        print(f"[script_generator] ciclo juez falló ({e}); ruta simple.", file=sys.stderr)
    return llm_script(topic, kind, angle, cfg) or template_script(topic, kind, angle)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic")
    ap.add_argument("--kind", default="evergreen")
    ap.add_argument("--angle", default="")
    ap.add_argument("--from-queue", action="store_true")
    args = ap.parse_args()
    topic, kind, angle = args.topic, args.kind, args.angle
    queue_categoria = None
    if args.from_queue:
        q = load_json(CONTENT / "queue.json", [])
        pending = [x for x in q if x.get("status") == "pending"]
        if not pending:
            print(json.dumps({"error": "cola vacía: corre trend_finder.py primero"})); return
        # ROTACIÓN POR DÉFICIT (§1d): el historial son las piezas ya producidas
        # (status != pending); se elige el pendiente cuya categoría esté más
        # por debajo de su % objetivo. La actualidad conserva prioridad dentro
        # de su categoría (va primero en la cola por construcción).
        produced = [x for x in q if x.get("status") != "pending"]
        counts = {}
        for x in produced:
            cat = mix_category(x.get("kind"), x.get("categoria_mezcla") or x.get("categoria"))
            counts[cat] = counts.get(cat, 0) + 1
        deficits = mix_deficits(counts, mix_pcts())
        nxt = max(pending, key=lambda x: deficits.get(
            mix_category(x.get("kind"), x.get("categoria_mezcla") or x.get("categoria")), 0))
        topic, kind, angle = nxt["topic"], nxt.get("kind", "evergreen"), nxt.get("angle", "")
        queue_categoria = nxt.get("categoria_mezcla") or nxt.get("categoria")
    if not topic:
        ap.error("falta --topic o --from-queue")
    script = generate(topic, kind, angle)
    if queue_categoria:
        script["categoria_mezcla"] = queue_categoria  # gana la categoría de la cola (§1d)
    slug = slugify(topic)
    out = CONTENT / "scripts"; out.mkdir(parents=True, exist_ok=True)
    save_json(out / f"{slug}.json", script)
    (out / f"{slug}.txt").write_text(script["full_text"], encoding="utf-8")
    script["slug"] = slug
    print(json.dumps(script, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
