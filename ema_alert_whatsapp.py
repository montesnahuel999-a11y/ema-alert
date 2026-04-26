"""
EMA 20/50/100 Alert - Forex - WhatsApp via Twilio
=================================================
Las credenciales se leen desde variables de entorno (Railway).
NO escribas tus datos directamente en este archivo.
"""

import os
import time
import logging
from datetime import datetime

import pandas as pd
import yfinance as yf
from twilio.rest import Client

# ─────────────────────────────────────────────
#  CONFIGURACIÓN — se leen desde Railway
# ─────────────────────────────────────────────

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN  = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM        = os.environ.get("TWILIO_FROM")   # ej: whatsapp:+14155238886
TWILIO_TO          = os.environ.get("TWILIO_TO")     # ej: whatsapp:+549XXXXXXXXXX

# Pares a monitorear (formato yfinance para forex)
PARES = [
    "EURUSD=X",
    "GBPUSD=X",
    "USDJPY=X",
    "AUDUSD=X",
]

# Parámetros de la estrategia
TOLERANCIA_EMA = 0.08
CALM_FACTOR    = 0.8
CALM_PROMEDIO  = 20

INTERVALO_SEG  = 300    # chequea cada 5 minutos
TIMEFRAME      = "15m"  # velas de 15 minutos
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
#  TWILIO
# ─────────────────────────────────────────────

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

def enviar_whatsapp(mensaje: str) -> None:
    try:
        twilio_client.messages.create(
            from_=TWILIO_FROM,
            to=TWILIO_TO,
            body=mensaje,
        )
        log.info(f"WhatsApp enviado: {mensaje}")
    except Exception as e:
        log.error(f"Error enviando WhatsApp: {e}")

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

    near_any = (
        ((close - ema20).abs()  < TOLERANCIA_EMA) |
        ((close - ema50).abs()  < TOLERANCIA_EMA) |
        ((close - ema100).abs() < TOLERANCIA_EMA)
    )

    body     = (close - open_).abs()
    avg_body = body.rolling(CALM_PROMEDIO).mean()
    calm     = body < (avg_body * CALM_FACTOR)
    calm_approach = calm & calm.shift(1) & calm.shift(2)

    alcista = (close > ema20) & (close > ema50) & (close > ema100)
    bajista = (close < ema20) & (close < ema50) & (close < ema100)

    long_base  = near_any & calm_approach & alcista
    short_base = near_any & calm_approach & bajista

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
    log.info("▶ Monitor EMA iniciado")
    log.info(f"  Pares:     {', '.join(PARES)}")
    log.info(f"  Intervalo: {INTERVALO_SEG}s  |  Timeframe: {TIMEFRAME}")

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
                    f"Toque suave EMA en {TIMEFRAME}\n"
                    f"Precio: {r['precio']:.5f}\n"
                    f"EMA20: {r['ema20']:.5f} | EMA50: {r['ema50']:.5f} | EMA100: {r['ema100']:.5f}\n"
                    f"Hora vela: {r['timestamp']}"
                )
                enviar_whatsapp(msg)
                marcar_notificado(par, r["timestamp"])

            elif r["short"] and not ya_notificado(par, r["timestamp"]):
                msg = (
                    f"📉 *SHORT - {nombre}*\n"
                    f"Toque suave EMA en {TIMEFRAME}\n"
                    f"Precio: {r['precio']:.5f}\n"
                    f"EMA20: {r['ema20']:.5f} | EMA50: {r['ema50']:.5f} | EMA100: {r['ema100']:.5f}\n"
                    f"Hora vela: {r['timestamp']}"
                )
                enviar_whatsapp(msg)
                marcar_notificado(par, r["timestamp"])

            else:
                log.info(f"{nombre}: sin señal")

        log.info(f"Próximo chequeo en {INTERVALO_SEG}s...\n")
        time.sleep(INTERVALO_SEG)


if __name__ == "__main__":
    main()
