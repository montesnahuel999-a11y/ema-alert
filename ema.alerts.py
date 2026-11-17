"""
Bot de Telegram: avisa la PRIMERA vela cerrada donde el precio toca la EMA 20, 50 o 100.
LONG : precio > EMA20, EMA50 y EMA100, y a menos de TOLERANCIA de alguna de las tres
SHORT: precio < EMA20, EMA50 y EMA100, y a menos de TOLERANCIA de alguna de las tres

Instalacion:  pip install yfinance pandas requests
Uso:          python ema_touch_bot.py
"""
import os
import time
import requests
import pandas as pd
import yfinance as yf

# ---------- CONFIGURACION ----------
# Mejor como variables de entorno (en Railway: Variables). Si pruebas en tu PC,
# puedes reemplazar el texto entre comillas, pero NO lo subas a GitHub.
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "PEGA_AQUI_EL_TOKEN_DE_BOTFATHER")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "PEGA_AQUI_TU_CHAT_ID")

# Simbolos de Yahoo Finance
SYMBOLS = {
    "EUR/USD": "EURUSD=X",
    "USD/CHF": "USDCHF=X",
}

INTERVAL = "1h"                # temporalidad de las velas
PERIOD = "60d"                 # historial a descargar (suficiente para EMA 100)
EMA_LENGTHS = [20, 50, 100]    # medias que se vigilan
TOLERANCIA_PCT = 0.0005        # 0.05%
CHECK_EVERY_SECONDS = 300      # cada 5 minutos
# -----------------------------------

last_alert = {}  # (nombre, lado) -> timestamp de la vela ya avisada


def send_telegram(text: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=15)
        if not r.ok:
            print("Error Telegram:", r.text)
    except requests.RequestException as e:
        print("Error de red enviando a Telegram:", e)


def zone(price: float, emas: dict):
    """Devuelve (is_long, is_short, lista de EMAs tocadas)."""
    tol = price * TOLERANCIA_PCT
    touched = [n for n, v in emas.items() if abs(price - v) < tol]
    all_below = all(price > v for v in emas.values())
    all_above = all(price < v for v in emas.values())
    return bool(touched) and all_below, bool(touched) and all_above, touched


def check_symbol(name: str, ticker: str) -> None:
    df = yf.download(ticker, period=PERIOD, interval=INTERVAL,
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        print(f"{name}: sin datos")
        return

    close = df["Close"]
    if isinstance(close, pd.DataFrame):  # yfinance a veces devuelve columnas multinivel
        close = close.iloc[:, 0]
    close = close.dropna()
    if len(close) < max(EMA_LENGTHS) + 5:
        print(f"{name}: pocos datos")
        return

    ema = {n: close.ewm(span=n, adjust=False).mean() for n in EMA_LENGTHS}

    # La ultima vela de Yahoo suele estar en formacion: usamos la penultima (cerrada)
    i, p = -2, -3
    emas_now = {n: float(ema[n].iloc[i]) for n in EMA_LENGTHS}
    emas_prev = {n: float(ema[n].iloc[p]) for n in EMA_LENGTHS}
    price = float(close.iloc[i])
    cur_long, cur_short, touched = zone(price, emas_now)
    prev_long, prev_short, _ = zone(float(close.iloc[p]), emas_prev)
    bar_time = close.index[i]

    for side, now, before in (("LONG", cur_long, prev_long), ("SHORT", cur_short, prev_short)):
        if now and not before and last_alert.get((name, side)) != bar_time:
            last_alert[(name, side)] = bar_time
            ema_txt = " | ".join(f"EMA{n}: {v:.5f}" for n, v in emas_now.items())
            send_telegram(
                f"{side} {name} ({INTERVAL})\n"
                f"Toca: {', '.join('EMA' + str(n) for n in touched)}\n"
                f"Precio: {price:.5f}\n"
                f"{ema_txt}\n"
                f"Vela cerrada: {bar_time}"
            )
            print(f"Alerta enviada: {side} {name}")


def main() -> None:
    send_telegram("Bot de toques EMA 20/50/100 iniciado (EUR/USD y USD/CHF).")
    while True:
        for name, ticker in SYMBOLS.items():
            try:
                check_symbol(name, ticker)
            except Exception as e:  # que un fallo no tire todo el bot
                print(f"Error en {name}: {e}")
        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()
