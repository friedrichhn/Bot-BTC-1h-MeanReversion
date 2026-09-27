import os
import time
import threading
from flask import Flask
import pandas as pd
import numpy as np
import requests
from binance.client import Client

# Servidor Flask para Web Service en Render
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot Estrategia 2 (Mean Reversion 1h) Operativo", 200

# Configuración de Binance Demo / Testnet
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

# Configuración de Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = Client(API_KEY, API_SECRET, testnet=True)
SYMBOL = "BTCUSDT"
TIMEFRAME = Client.KLINE_INTERVAL_1HOUR
LEVERAGE = 10  # Configurado a 10x

def send_telegram_alert(message):
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown"
            }
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            print(f"⚠️ Error enviando alerta a Telegram: {e}", flush=True)

def init_leverage():
    try:
        client.futures_change_leverage(symbol=SYMBOL, leverage=LEVERAGE)
        print(f"⚙️ [Estrategia 2 - 1h] Apalancamiento configurado a {LEVERAGE}x en {SYMBOL}", flush=True)
    except Exception as e:
        print(f"⚠️ [Estrategia 2 - 1h] Error configurando apalancamiento: {e}", flush=True)

def get_market_data():
    klines = client.futures_klines(symbol=SYMBOL, interval=TIMEFRAME, limit=100)
    df = pd.DataFrame(klines, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
    ])
    df['close'] = df['close'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    
    # 1. Z-Score (20 periodos)
    window = 20
    sma = df['close'].rolling(window=window).mean()
    std = df['close'].rolling(window=window).std()
    df['z_score'] = (df['close'] - sma) / std
    
    # 2. RSI (14 periodos)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # 3. ADX (14 periodos)
    df['tr'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift(1)),
            abs(df['low'] - df['close'].shift(1))
        )
    )
    df['atr'] = df['tr'].rolling(window=14).mean()
    
    up_move = df['high'] - df['high'].shift(1)
    down_move = df['low'].shift(1) - df['low']
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    
    plus_di = 100 * (pd.Series(plus_dm).rolling(14).mean() / df['atr'])
    minus_di = 100 * (pd.Series(minus_dm).rolling(14).mean() / df['atr'])
    
    dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di))
    df['adx'] = dx.rolling(14).mean()
    
    return df

def run_trading_bot():
    print(f"🚀 Iniciando Bucle de Monitoreo - Estrategia 2 (Mean Reversion 1h) | {SYMBOL}", flush=True)
    init_leverage()
    
    # Mensaje de confirmación de arranque a Telegram
    send_telegram_alert("🤖 *Bot Estrategia 2 (1h Mean Reversion)* iniciado correctamente en Render.")
    
    last_processed_time = None
    
    while True:
        try:
            df = get_market_data()
            last_closed = df.iloc[-2]  # Anteúltima fila: vela de 1 hora cerrada
            candle_time = last_closed['timestamp']
            
            if candle_time != last_processed_time:
                close_price = last_closed['close']
                z_score = last_closed['z_score']
                rsi = last_closed['rsi']
                adx = last_closed['adx']
                
                timestamp_str = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(candle_time/1000))
                print(f"[{timestamp_str} UTC] VELA 1H CERRADA | Precio: ${close_price:.2f} | Z-Score: {z_score:.2f} | RSI: {rsi:.2f} | ADX: {adx:.2f}", flush=True)
                
                # CONDICIÓN LONG (Sobrevendido en Rango)
                if z_score < -2.0 and rsi < 35 and adx < 20:
                    msg = (
                        f"🟢 *SEÑAL LONG DETECTADA (10x)*\n\n"
                        f"*Estrategia:* 2 (1h Mean Reversion)\n"
                        f"*Par:* {SYMBOL}\n"
                        f"*Precio:* ${close_price:.2f}\n"
                        f"*Z-Score:* {z_score:.2f} | *RSI:* {rsi:.2f} | *ADX:* {adx:.2f}"
                    )
                    print(msg, flush=True)
                    send_telegram_alert(msg)
                    
                # CONDICIÓN SHORT (Sobrecomprado en Rango)
                elif z_score > 2.0 and rsi > 65 and adx < 20:
                    msg = (
                        f"🔴 *SEÑAL SHORT DETECTADA (10x)*\n\n"
                        f"*Estrategia:* 2 (1h Mean Reversion)\n"
                        f"*Par:* {SYMBOL}\n"
                        f"*Precio:* ${close_price:.2f}\n"
                        f"*Z-Score:* {z_score:.2f} | *RSI:* {rsi:.2f} | *ADX:* {adx:.2f}"
                    )
                    print(msg, flush=True)
                    send_telegram_alert(msg)
                    
                else:
                    reasons = []
                    if adx >= 20: reasons.append(f"ADX alto para rango ({adx:.1f} >= 20)")
                    if abs(z_score) <= 2.0: reasons.append(f"Z-Score dentro de rango ({z_score:.2f})")
                    if rsi >= 35 and rsi <= 65: reasons.append(f"RSI en zona neutral ({rsi:.1f})")
                    print(f"ℹ️ Sin entrada 1H. Motivo: {', '.join(reasons)}", flush=True)
                    
                last_processed_time = candle_time
                
        except Exception as e:
            print(f"❌ Error en el ciclo principal 1H: {e}", flush=True)
            
        time.sleep(60)

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_trading_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    run_flask()
