# Version Auto-Trade Binance Futures Testnet - Mean Reversion 1h
import os
import time
import threading
from flask import Flask
import pandas as pd
import numpy as np
import requests
from binance.client import Client

app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot Estrategia 2 (Mean Reversion 1h Autotrade) Operativo", 200

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = Client(API_KEY, API_SECRET, testnet=True)
SYMBOL = "BTCUSDT"
TIMEFRAME = Client.KLINE_INTERVAL_1HOUR
LEVERAGE = 10
INITIAL_CAPITAL = 400  # Capital en USD

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

def execute_binance_trade(side, close_price, tp_price, sl_price):
    try:
        notional_value = INITIAL_CAPITAL * LEVERAGE
        quantity = round(notional_value / close_price, 3)
        
        # 1. Orden de Mercado Principal
        order = client.futures_create_order(
            symbol=SYMBOL,
            side=side,
            type='MARKET',
            quantity=quantity
        )
        print(f"✅ Orden de Mercado Ejecutada en Binance: {side} {quantity} BTC", flush=True)
        
        # Dirección opuesta para cerrar la posición
        tp_side = 'SELL' if side == 'BUY' else 'BUY'
        
        # 2. Take Profit con cantidad explícita (sin closePosition)
        client.futures_create_order(
            symbol=SYMBOL,
            side=tp_side,
            type='TAKE_PROFIT_MARKET',
            stopPrice=round(tp_price, 2),
            quantity=quantity
        )
        
        # 3. Stop Loss con cantidad explícita (sin closePosition)
        client.futures_create_order(
            symbol=SYMBOL,
            side=tp_side,
            type='STOP_MARKET',
            stopPrice=round(sl_price, 2),
            quantity=quantity
        )
        
        return f"🚀 *ORDEN EJECUTADA EN BINANCE TESTNET*\nCantidad: `{quantity} BTC` (${notional_value} Notional)"
    
    except Exception as e:
        err_msg = f"❌ Error ejecutando orden en Binance: {e}"
        print(err_msg, flush=True)
        return f"⚠️ *Error al ejecutar en Binance:* {e}"

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
    
    df['sma20'] = df['close'].rolling(window=20).mean()
    df['std20'] = df['close'].rolling(window=20).std()
    df['z_score'] = (df['close'] - df['sma20']) / df['std20']
    
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
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
    print("🚀 Bucle de Monitoreo Iniciado - Estrategia 2 (1h)", flush=True)
    init_leverage()
    send_telegram_alert("🤖 Bot Estrategia 2 (Mean Reversion 1h Auto-Trade) activo en Render.")
    
    last_processed_time = None
    
    while True:
        try:
            df = get_market_data()
            last_closed = df.iloc[-2]
            candle_time = last_closed['timestamp']
            
            if candle_time != last_processed_time:
                close_price = last_closed['close']
                z_score = last_closed['z_score']
                rsi = last_closed['rsi']
                adx = last_closed['adx']
                atr = last_closed['atr']
                
                timestamp_str = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(candle_time/1000))
                print("VELA 1H CERRADA -> Precio:", close_price, "Z-Score:", z_score, "RSI:", rsi, "ADX:", adx, flush=True)
                
                if (z_score < -2.0) and (rsi < 35) and (adx < 30):
                    tp_price = close_price + (atr * 1.5)
                    sl_price = close_price - (atr * 1.0)
                    exec_status = execute_binance_trade('BUY', close_price, tp_price, sl_price)
                    
                    msg = (
                        f"🟢 *SEÑAL MEAN REVERSION LONG DETECTADA (10x)*\n\n"
                        f"*Estrategia:* 2 (Mean Reversion 1h)\n"
                        f"*Par:* {SYMBOL}\n"
                        f"*Precio Entrada:* ${close_price:.2f}\n"
                        f"*Take Profit:* ${tp_price:.2f}\n"
                        f"*Stop Loss:* ${sl_price:.2f}\n\n"
                        f"{exec_status}"
                    )
                    print(msg, flush=True)
                    send_telegram_alert(msg)
                    
                elif (z_score > 2.0) and (rsi > 65) and (adx < 30):
                    tp_price = close_price - (atr * 1.5)
                    sl_price = close_price + (atr * 1.0)
                    exec_status = execute_binance_trade('SELL', close_price, tp_price, sl_price)
                    
                    msg = (
                        f"🔴 *SEÑAL MEAN REVERSION SHORT DETECTADA (10x)*\n\n"
                        f"*Estrategia:* 2 (Mean Reversion 1h)\n"
                        f"*Par:* {SYMBOL}\n"
                        f"*Precio Entrada:* ${close_price:.2f}\n"
                        f"*Take Profit:* ${tp_price:.2f}\n"
                        f"*Stop Loss:* ${sl_price:.2f}\n\n"
                        f"{exec_status}"
                    )
                    print(msg, flush=True)
                    send_telegram_alert(msg)
                    
                else:
                    reasons = []
                    if abs(z_score) <= 2.0: reasons.append(f"Z-Score dentro de rango ({z_score:.2f})")
                    if adx >= 30: reasons.append(f"ADX muy alto / tendencia fuerte ({adx:.1f})")
                    if z_score < -2.0 and rsi >= 35: reasons.append(f"RSI alto para compra ({rsi:.1f})")
                    if z_score > 2.0 and rsi <= 65: reasons.append(f"RSI bajo para venta ({rsi:.1f})")
                    print("Sin entrada 1H. Motivo:", ", ".join(reasons), flush=True)
                    
                last_processed_time = candle_time
                
        except Exception as e:
            print("Error en ciclo 1H:", e, flush=True)
            time.sleep(120)
            continue
            
        time.sleep(30)

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_trading_bot)
    bot_thread.daemon = True
    bot_thread.start()
    run_flask()
