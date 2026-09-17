"""
Monitor de Noticias Financieras + Calendario Económico - Telegram
=================================================================
- Revisa RSS de noticias (BBC, Investing.com, WSJ) y traduce al español.
- Marca con 🔴 las noticias de alta importancia (Fed, BCE, FOMC) o que
  mencionan pares clave (EURUSD, GBPUSD, USDJPY, USDCAD).
- Revisa el calendario económico de ForexFactory y avisa próximos eventos
  de alto impacto en esas mismas divisas.

Las credenciales se leen desde variables de entorno (GitHub Actions).
NO escribas tus datos directamente en este archivo.

INSTALAR DEPENDENCIAS:
    pip install feedparser requests deep-translator

CORRER:
    python news_monitor.py
"""

import os
import json
import logging
import requests
import feedparser
from datetime import datetime, timedelta, timezone
from deep_translator import GoogleTranslator

# ─────────────────────────────────────────────
#  CONFIGURACIÓN
# ─────────────────────────────────────────────

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Fuentes RSS. Podés agregar/quitar líneas libremente.
# NOTA: Bloomberg no tiene RSS público gratuito.
FUENTES = {
    "BBC Business":             "http://feeds.bbci.co.uk/news/business/rss.xml",
    "Investing.com - Noticias": "https://www.investing.com/rss/news_25.rss",
    "Investing.com - Forex":    "https://www.investing.com/rss/news_1.rss",
    "WSJ - Markets":            "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
}

# Palabras clave para filtrar (dejar vacío [] = manda todas las noticias de las fuentes de arriba)
PALABRAS_CLAVE = []

# Palabras que EXCLUYEN una noticia (dejar vacío [] = no excluye nada)
PALABRAS_EXCLUIDAS = []

# ── Marcado de importancia (NO filtra, solo agrega 🔴 al mensaje) ──
PALABRAS_ALTA_IMPORTANCIA = [
    "fed", "fomc", "federal reserve", "powell",
    "ecb", "bce", "banco central europeo", "lagarde",
    "interest rate", "tasa de interés", "tasas de interés", "rate decision",
    "rate hike", "rate cut", "subida de tipos", "recorte de tasas",
    "nfp", "nonfarm payrolls", "nómina no agrícola",
    "inflación", "inflation", "cpi", "ipc",
]

# Pares/divisas que te interesan especialmente
ACTIVOS_RELEVANTES = [
    "eurusd", "eur/usd", "euro",
    "gbpusd", "gbp/usd", "libra esterlina", "pound sterling",
    "usdjpy", "usd/jpy", "yen",
    "usdcad", "usd/cad", "dólar canadiense", "canadian dollar",
]

# Traducción automática de inglés -> español
TRADUCIR = True

ARCHIVO_ESTADO = "noticias_enviadas.json"
MAX_IDS_GUARDADOS_POR_FUENTE = 200

# ── Calendario económico (ForexFactory, endpoint JSON no oficial usado por la comunidad) ──
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
DIVISAS_CALENDARIO = ["USD", "EUR", "GBP", "JPY", "CAD"]
IMPACTO_MINIMO = "High"  # High, Medium, Low (según lo clasifica ForexFactory)
AVISAR_MINUTOS_ANTES = 60  # avisar cuando falten <= 60 min para el evento
ARCHIVO_ESTADO_CALENDARIO = "calendario_avisado.json"

# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  TELEGRAM
# ─────────────────────────────────────────────

def enviar_telegram(mensaje: str) -> None:
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        }
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            log.info(f"Telegram enviado: {mensaje[:60]}...")
        else:
            log.error(f"Error Telegram: {r.text}")
    except Exception as e:
        log.error(f"Error enviando Telegram: {e}")

# ─────────────────────────────────────────────
#  TRADUCCIÓN
# ─────────────────────────────────────────────

def traducir(texto: str) -> str:
    if not TRADUCIR or not texto:
        return texto
    try:
        return GoogleTranslator(source="auto", target="es").translate(texto)
    except Exception as e:
        log.warning(f"No se pudo traducir, se usa el original: {e}")
        return texto

# ─────────────────────────────────────────────
#  ESTADO (para no repetir noticias/eventos ya enviados)
# ─────────────────────────────────────────────

def cargar_json(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.error(f"No se pudo leer {path}: {e}")
    return {}

def guardar_json(path: str, data: dict) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"No se pudo guardar {path}: {e}")

# ─────────────────────────────────────────────
#  NOTICIAS (RSS)
# ─────────────────────────────────────────────

def pasa_filtro(titulo: str, resumen: str) -> bool:
    texto = f"{titulo} {resumen}".lower()
    if any(p.lower() in texto for p in PALABRAS_EXCLUIDAS):
        return False
    if not PALABRAS_CLAVE:
        return True
    return any(p.lower() in texto for p in PALABRAS_CLAVE)

def es_alta_importancia(titulo: str, resumen: str) -> bool:
    texto = f"{titulo} {resumen}".lower()
    if any(p.lower() in texto for p in PALABRAS_ALTA_IMPORTANCIA):
        return True
    if any(p.lower() in texto for p in ACTIVOS_RELEVANTES):
        return True
    return False

def procesar_fuente(nombre_fuente: str, url_feed: str, estado: dict) -> int:
    enviadas = 0
    ids_previos = set(estado.get(nombre_fuente, []))
    ids_nuevos = list(ids_previos)

    try:
        feed = feedparser.parse(url_feed)
    except Exception as e:
        log.error(f"{nombre_fuente}: error al leer feed — {e}")
        return 0

    if feed.bozo and not feed.entries:
        log.warning(f"{nombre_fuente}: feed vacío o con error ({feed.bozo_exception})")
        return 0

    for entrada in reversed(feed.entries):
        id_unico = entrada.get("id") or entrada.get("link")
        if not id_unico or id_unico in ids_previos:
            continue

        titulo_original = entrada.get("title", "Sin título")
        link = entrada.get("link", "")
        resumen = entrada.get("summary", "")

        if pasa_filtro(titulo_original, resumen):
            titulo_es = traducir(titulo_original)
            importante = es_alta_importancia(titulo_original, resumen)
            emoji = "🔴" if importante else "📰"

            mensaje = f"{emoji} {nombre_fuente}\n{titulo_es}\n{link}"
            enviar_telegram(mensaje)
            enviadas += 1

        ids_nuevos.append(id_unico)

    estado[nombre_fuente] = ids_nuevos[-MAX_IDS_GUARDADOS_POR_FUENTE:]
    return enviadas

def procesar_noticias():
    estado = cargar_json(ARCHIVO_ESTADO)
    primera_corrida = not os.path.exists(ARCHIVO_ESTADO)

    total_enviadas = 0
    for nombre_fuente, url_feed in FUENTES.items():
        if primera_corrida:
            try:
                feed = feedparser.parse(url_feed)
                ids = [e.get("id") or e.get("link") for e in feed.entries]
                estado[nombre_fuente] = ids[:MAX_IDS_GUARDADOS_POR_FUENTE]
                log.info(f"{nombre_fuente}: primera corrida, se guardan {len(ids)} noticias existentes sin enviar.")
            except Exception as e:
                log.error(f"{nombre_fuente}: error en primera corrida — {e}")
        else:
            enviadas = procesar_fuente(nombre_fuente, url_feed, estado)
            total_enviadas += enviadas
            log.info(f"{nombre_fuente}: {enviadas} noticias nuevas enviadas.")

    guardar_json(ARCHIVO_ESTADO, estado)
    log.info(f"Total noticias enviadas esta corrida: {total_enviadas}")

# ─────────────────────────────────────────────
#  CALENDARIO ECONÓMICO (ForexFactory)
# ─────────────────────────────────────────────

def procesar_calendario():
    try:
        r = requests.get(CALENDAR_URL, timeout=15)
        r.raise_for_status()
        eventos = r.json()
    except Exception as e:
        log.error(f"No se pudo leer el calendario económico: {e}")
        return

    avisados = cargar_json(ARCHIVO_ESTADO_CALENDARIO)
    ids_avisados = set(avisados.get("ids", []))
    nuevos_avisados = list(ids_avisados)

    ahora = datetime.now(timezone.utc)
    enviados = 0

    for ev in eventos:
        moneda = ev.get("country", "")
        impacto = ev.get("impact", "")
        titulo = ev.get("title", "Evento económico")
        fecha_str = ev.get("date")  # formato ISO con offset, según el feed

        if moneda not in DIVISAS_CALENDARIO:
            continue
        if impacto != IMPACTO_MINIMO:
            continue
        if not fecha_str:
            continue

        try:
            fecha_evento = datetime.fromisoformat(fecha_str)
            if fecha_evento.tzinfo is None:
                fecha_evento = fecha_evento.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        id_evento = f"{moneda}{titulo}{fecha_str}"
        if id_evento in ids_avisados:
            continue

        minutos_para_evento = (fecha_evento - ahora).total_seconds() / 60

        if 0 <= minutos_para_evento <= AVISAR_MINUTOS_ANTES:
            titulo_es = traducir(titulo)
            hora_local = fecha_evento.astimezone().strftime("%H:%M")
            mensaje = (
                f"🔴📅 Calendario Económico - Alto Impacto\n"
                f"{moneda} — {titulo_es}\n"
                f"Hora: {hora_local} (en ~{int(minutos_para_evento)} min)"
            )
            enviar_telegram(mensaje)
            nuevos_avisados.append(id_evento)
            enviados += 1

    guardar_json(ARCHIVO_ESTADO_CALENDARIO, {"ids": nuevos_avisados[-500:]})
    log.info(f"Calendario económico: {enviados} eventos avisados esta corrida.")

# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main():
    log.info("▶️ Monitor de Noticias + Calendario Económico - Telegram")
    procesar_noticias()
    procesar_calendario()


if __name__ == "__main__":
    main()
