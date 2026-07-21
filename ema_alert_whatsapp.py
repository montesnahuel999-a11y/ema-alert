"""
EMA 20/50/100 Alert - Forex - Telegram
=================================================
Las credenciales se leen desde variables de entorno (GitHub Actions).
NO escribas tus datos directamente en este archivo.
"""

import os
import time
import logging
import requests

import pandas as pd
import yfinance as yf

# ─────────────────────────────────────────────
#  CONFIGURACIÓN — se leen desde variables de entorno
# ─────────────────────────────────────────────

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Pares a monitorear (formato yfinance para forex)
PARES = [
    "EURUSD=X",
    "USDJPY=X",
    "GBPUSD=X",
    "AUDUSD=X",   # Dólar Australiano
    "USDCAD=X",   # Dólar Canadiense
    "^GSPC",      # S&P 500
]

# Nombres legibles para cada par
NOMBRES = {
    "EURUSD=X": "EURUSD",
    "USDJPY=X": "USDJPY",
    "GBPUSD=X": "GBPUSD",
    "AUDUSD=X": "AUDUSD",
    "USDCAD=X": "USDCAD",
    "^GSPC":    "SP500",
}

# Tolerancia dinámica basada en porcentaje del precio (0.05%)
TOLERANCIA_PCT = 0.0005

TIMEFRAME      = "4h"   # velas de 4 horas
PERIODOS_DATOS = "60d"

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
#  LOOP PRINCIPAL — corre una vez y termina
# ─────────────────────────────────────────────

def main():
    log.info("▶ Monitor EMA - Telegram")
    log.info(f"  Pares:     {', '.join(PARES)}")
    log.info(f"  Timeframe: {TIMEFRAME}")

    for par in PARES:
        try:
            r = calcular_señales(par)
        except Exception as e:
            log.error(f"{par}: error — {e}")
            continue

        nombre = NOMBRES.get(par, par.replace("=X", ""))

        # El SP500 cotiza en puntos de índice, usamos 2 decimales
        decimales = 2 if par == "^GSPC" else 5

        if r["long"]:
            msg = (
                f"📈 *LONG - {nombre}*\n"
                f"Toque EMA en {TIMEFRAME}\n"
                f"Precio: {r['precio']:.{decimales}f}\n"
                f"EMA20: {r['ema20']:.{decimales}f} | EMA50: {r['ema50']:.{decimales}f} | EMA100: {r['ema100']:.{decimales}f}\n"
                f"Hora vela: {r['timestamp']}"
            )
            enviar_telegram(msg)

        elif r["short"]:
            msg = (
                f"📉 *SHORT - {nombre}*\n"
                f"Toque EMA en {TIMEFRAME}\n"
                f"Precio: {r['precio']:.{decimales}f}\n"
                f"EMA20: {r['ema20']:.{decimales}f} | EMA50: {r['ema50']:.{decimales}f} | EMA100: {r['ema100']:.{decimales}f}\n"
                f"Hora vela: {r['timestamp']}"
            )
            enviar_telegram(msg)

        else:
            log.info(f"{nombre}: sin señal")


if __name__ == "__main__":
    main()
