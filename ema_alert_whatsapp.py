"""
EMA 20/50/100 Alert - Forex - Telegram
=================================================
Las credenciales se leen desde variables de entorno (Railway).
NO escribas tus datos directamente en este archivo.
"""

import os
import time
import logging
import requests

import pandas as pd
import yfinance as yf

# ─────────────────────────────────────────────
#  CONFIGURACIÓN — se leen desde Railway
# ─────────────────────────────────────────────

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Pares a monitorear (formato yfinance para forex)
PARES = [
    "EURUSD=X",
    "USDJPY=X",
    "GBPUSD=X",
]

# Tolerancia en porcentaje del precio (0.05%)
TOLERANCIA_PCT = 0.0005

INTERVALO_SEG  = 300    # chequea cada 5 minutos
TIMEFRAME      = "30m"  # velas de 30 minutos
PERIODOS_DATOS = "7d"

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
            "parse_mode": "Markdown"
        }
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            log.info(f"Telegram enviado: {mensaje[:50]}...")
        else:
            log.error(f"Error Telegram: {r.text}")
    except Exception as e:
        log.error(f"Error enviando Telegram: {e}")

# ─────────────────────────────────────────────
#  LÓGICA DE ESTRATEGIA
# ─────────────────────────────────────────────

def calcular_señales(par: str) -> dict:
    df = yf.download(
        par,
        period=PERIODOS_DATOS,
        interval=TIMEFRAME,
        progress=False,
        auto_adjust=True,
    )

    if df.empty or len(df) < 110:
        log.warning(f"{par}: datos insuficientes ({len(df)} velas)")
        return {"long": False, "short": False}

    close = df["Close"].squeeze()
    open_ = df["Open"].squeeze()

    ema20  = close.ewm(span=20,  adjust=False).mean()
    ema50  = close.ewm(span=50,  adjust=False).mean()
    ema100 = close.ewm(span=100, adjust=False).mean()

    # Tolerancia dinámica basada en porcentaje del precio
    tolerancia = close * TOLERANCIA_PCT

    near_any = (
        ((close - ema20).abs()  < tolerancia) |
        ((close - ema50).abs()  < tolerancia) |
        ((close - ema100).abs() < tolerancia)
    )

    alcista = (close > ema20) & (close > ema50) & (close > ema100)
    bajista = (close < ema20) & (close < ema50) & (close < ema100)

    long_base  = near_any & alcista
    short_base = near_any & bajista

    long_signal  = long_base  & ~long_base.shift(1).fillna(False)
    short_signal = short_base & ~short_base.shift(1).fillna(False)

    idx = -2

    return {
        "long":      bool(long_signal.iloc[idx]),
        "short":     bool(short_signal.iloc[idx]),
        "precio":    float(close.iloc[idx]),
        "ema20":     float(ema20.iloc[idx]),
        "ema50":     float(ema50.iloc[idx]),
        "ema100":    float(ema100.iloc[idx]),
        "timestamp": df.index[idx],
    }

# ─────────────────────────────────────────────
#  ESTADO — evita notificaciones duplicadas
# ─────────────────────────────────────────────

ultimo_aviso: dict = {}

def ya_notificado(par: str, ts) -> bool:
    return ultimo_aviso.get(par) == ts

def marcar_notificado(par: str, ts) -> None:
    ultimo_aviso[par] = ts

# ─────────────────────────────────────────────
#  LOOP PRINCIPAL
# ─────────────────────────────────────────────

def main():
    log.info("▶ Monitor EMA iniciado - Telegram")
    log.info(f"  Pares:     {', '.join(PARES)}")
    log.info(f"  Intervalo: {INTERVALO_SEG}s  |  Timeframe: {TIMEFRAME}")
    log.info(f"  Tolerancia: {TOLERANCIA_PCT*100}% del precio")

    while True:
        for par in PARES:
            try:
                r = calcular_señales(par)
            except Exception as e:
                log.error(f"{par}: error — {e}")
                continue

            nombre = par.replace("=X", "")

            if r["long"] and not ya_notificado(par, r["timestamp"]):
                msg = (
                    f"📈 *LONG - {nombre}*\n"
                    f"Toque EMA en {TIMEFRAME}\n"
                    f"Precio: {r['precio']:.5f}\n"
                    f"EMA20: {r['ema20']:.5f} | EMA50: {r['ema50']:.5f} | EMA100: {r['ema100']:.5f}\n"
                    f"Hora vela: {r['timestamp']}"
                )
                enviar_telegram(msg)
                marcar_notificado(par, r["timestamp"])

            elif r["short"] and not ya_notificado(par, r["timestamp"]):
                msg = (
                    f"📉 *SHORT - {nombre}*\n"
                    f"Toque EMA en {TIMEFRAME}\n"
                    f"Precio: {r['precio']:.5f}\n"
                    f"EMA20: {r['ema20']:.5f} | EMA50: {r['ema50']:.5f} | EMA100: {r['ema100']:.5f}\n"
                    f"Hora vela: {r['timestamp']}"
                )
                enviar_telegram(msg)
                marcar_notificado(par, r["timestamp"])

            else:
                log.info(f"{nombre}: sin señal")

        log.info(f"Próximo chequeo en {INTERVALO_SEG}s...\n")
        time.sleep(INTERVALO_SEG)


if __name__ == "__main__":
    main()
