# Versión Auto-trade Binance Futures Testnet - Estrategia 2 (Mean Reversion 1h con Control de Posición)
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
    return "Bot Estrategia 2 (Mean Reversion 1h) Operativo", 200

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

client = Client(API_KEY, API_SECRET, testnet=True)
SYMBOL = "BTCUSDT"
TIMEFRAME = Client.KLINE_INTERVAL_1HOUR
LEVERAGE = 10
INITIAL_CAPITAL = 350  # Capital asignado en USDT

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
        print(f"⚙️ [Estrategia 2] Apalancamiento configurado a {LEVERAGE}x en {SYMBOL}", flush=True)
    except Exception as e:
        print(f"⚠️ [Estrategia 2] Error configurando apalancamiento: {e}", flush=True)

def has_open_position():
    """Verifica si ya hay una posición abierta o órdenes pendientes de protección en Binance."""
    try:
        # 1. Revisar si hay contratos abiertos
        positions = client.futures_position_information(symbol=SYMBOL)
        for pos in positions:
            if float(pos['positionAmt']) != 0.0:
                return True
        
        # 2. Revisar si hay órdenes pendientes (TP / SL activos)
        open_orders = client.futures_get_open_orders(symbol=SYMBOL)
        if len(open_orders) > 0:
            return True
            
        return False
    except Exception as e:
        print(f"⚠️ Error consultando posición actual en Binance (Estrategia 2): {e}", flush=True)
        return True

def execute_binance_trade(side, close_price, tp_price, sl_price):
    try:
        # Validación estricta de posición única
        if has_open_position():
            print("🛡️ [Protección Estrategia 2] Ya existe una posición u órdenes abiertas. Se bloquea la entrada.", flush=True)
            return None

        notional_value = INITIAL_CAPITAL * LEVERAGE
        quantity = round(notional_value / close_price, 3)
        
        # 1. Orden de Mercado Principal
        client.futures_create_order(
            symbol=SYMBOL,
            side=side,
            type='MARKET',
            quantity=quantity
        )
        print(f"✅ [Estrategia 2] Orden de Mercado Ejecutada en Binance: {side} {quantity} BTC", flush=True)
        
        # Dirección opuesta para cerrar la posición
        tp_side = 'SELL' if side == 'BUY' else 'BUY'
        
        # 2. Take Profit
        client.futures_create_order(
            symbol=SYMBOL,
            side=tp_side,
            type='TAKE_PROFIT_MARKET',
            stopPrice=round(tp_price, 2),
            quantity=quantity
        )
        
        # 3. Stop Loss
        client.futures_create_order(
            symbol=SYMBOL,
            side=tp_side,
            type='STOP_MARKET',
            stopPrice=round(sl_price, 2),
            quantity=quantity
        )
        
        return f"🚀 *ESTRATEGIA 2 - ORDEN EJECUTADA*\nCantidad: `{quantity} BTC` (${notional_value} Notional)"
    
    except Exception as e:
        err_msg = f"❌ Error ejecutando orden de Estrategia 2 en Binance: {e}"
        print(err_msg, flush=True)
        return f"⚠️ *Error al ejecutar Estrategia 2:* {e}"

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
    
    # Indicadores para Mean Reversion (Bandas de Bollinger + RSI)
    df['sma20'] = df['close'].rolling(window=20).mean()
    df['std20'] = df['close'].rolling(window=20).std()
    df['upper_band'] = df['sma20'] + (df['std20'] * 2)
    df['lower_band'] = df['sma20'] - (df['std20'] * 2)
    
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
    
    return df

def run_trading_bot():
    print("🚀 Bucle de Monitoreo Iniciado - Estrategia 2 (Mean Reversion 1h)", flush=True)
    init_leverage()
    send_telegram_alert("🤖 Bot Estrategia 2 (Mean Reversion 1h con Control de Posición) activo.")
    
    last_processed_time = None
    
    while True:
        try:
            df = get_market_data()
            last_closed = df.iloc[-2]
            candle_time = last_closed['timestamp']
            
            if candle_time != last_processed_time:
                close_price = last_closed['close']
                lower_band = last_closed['lower_band']
                upper_band = last_closed['upper_band']
                sma20 = last_closed['sma20']
                rsi = last_closed['rsi']
                atr = last_closed['atr']
                
                print(f"VELA 1H CERRADA -> Precio: {close_price}, Lower: {lower_band:.2f}, Upper: {upper_band:.2f}, RSI: {rsi:.1f}", flush=True)
                
                # Validación de posición única
                if has_open_position():
                    print("⏳ Posición u órdenes activas detectadas en Estrategia 2. Esperando el cierre...", flush=True)
                else:
                    # Regla de Compra (Long): Precio cae por debajo de la banda inferior y RSI está en sobreventa (< 30)
                    if (close_price < lower_band) and (rsi < 30):
                        tp_price = sma20  # Apunta de regreso a la media móvil central
                        sl_price = close_price - (atr * 1.5)
                        exec_status = execute_binance_trade('BUY', close_price, tp_price, sl_price)
                        
                        if exec_status:
                            msg = (
                                f"🟢 *ESTRATEGIA 2 - MEAN REVERSION LONG (10x)*\n\n"
                                f"*Par:* {SYMBOL} (1h)\n"
                                f"*Precio Entrada:* ${close_price:.2f}\n"
                                f"*Take Profit (Media):* ${tp_price:.2f}\n"
                                f"*Stop Loss:* ${sl_price:.2f}\n\n"
                                f"{exec_status}"
                            )
                            print(msg, flush=True)
                            send_telegram_alert(msg)
                        
                    # Regla de Venta (Short): Precio sube por encima de la banda superior y RSI está en sobrecompra (> 70)
                    elif (close_price > upper_band) and (rsi > 70):
                        tp_price = sma20  # Apunta de regreso a la media móvil central
                        sl_price = close_price + (atr * 1.5)
                        exec_status = execute_binance_trade('SELL', close_price, tp_price, sl_price)
                        
                        if exec_status:
                            msg = (
                                f"🔴 *ESTRATEGIA 2 - MEAN REVERSION SHORT (10x)*\n\n"
                                f"*Par:* {SYMBOL} (1h)\n"
                                f"*Precio Entrada:* ${close_price:.2f}\n"
                                f"*Take Profit (Media):* ${tp_price:.2f}\n"
                                f"*Stop Loss:* ${sl_price:.2f}\n\n"
                                f"{exec_status}"
                            )
                            print(msg, flush=True)
                            send_telegram_alert(msg)
                        
                    else:
                        print("Sin condiciones de reversión cumplidas en esta vela de 1h.", flush=True)
                    
                last_processed_time = candle_time
                
        except Exception as e:
            print("Error en ciclo de Estrategia 2:", e, flush=True)
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
