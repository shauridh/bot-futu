import ccxt
import pandas as pd
import time
import os
import requests
import sys
from datetime import datetime

# --- KONFIGURASI ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- PAIR YANG DIPANTAU (LIQUID ASSETS) ---
SYMBOLS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
    'DOGE/USDT', 'ADA/USDT', 'AVAX/USDT', 'LINK/USDT', 'TRX/USDT',
    'MATIC/USDT', 'LTC/USDT', 'DOT/USDT', 'SHIB/USDT', 'NEAR/USDT'
]

TIMEFRAME = '1h'         
LEVERAGE = 10  # Naikkan sedikit leverage karena SL lebih ketat

# Memory Posisi
active_trades = {}

print(f"--- STARTING AGGRESSIVE BOT ({len(SYMBOLS)} Pairs) ---")

try:
    exchange = ccxt.binance({'options': {'defaultType': 'future'}})
    exchange.load_markets()
    print("✅ Koneksi Binance OK.")
except Exception as e:
    print(f"❌ Error Init: {e}")
    sys.exit(1)

def send_telegram(msg):
    if not TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try: requests.post(url, data=data, timeout=10)
    except: pass

def calculate_indicators(df):
    # 1. EMA DIPERCEPAT (7 & 14) agar entry lebih awal
    df['EMA_FAST'] = df['close'].ewm(span=7, adjust=False).mean()
    df['EMA_SLOW'] = df['close'].ewm(span=14, adjust=False).mean()
    
    # 2. EMA 200 untuk Tren Besar (Filter Utama)
    df['EMA_TREND'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # 3. RSI (Untuk validasi agar tidak beli di pucuk)
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
    loss = -delta.where(delta < 0, 0).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # 4. ATR untuk SL/TP Dinamis
    df['tr1'] = df['high'] - df['low']
    df['tr2'] = abs(df['high'] - df['close'].shift())
    df['tr3'] = abs(df['low'] - df['close'].shift())
    df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
    df['ATR'] = df['tr'].rolling(window=14).mean()
    
    return df

def get_data(symbol):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=205)
        df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        return calculate_indicators(df)
    except: return None

def open_position(symbol, action, price, atr, rsi):
    # SL lebih ketat (1.2x ATR) biar kalau salah loss dikit
    sl_pips = atr * 1.2
    
    if action == 'LONG':
        sl_real = price - sl_pips
        tp_real = price + (sl_pips * 2.5) # Risk Reward 1:2.5
    else: # SHORT
        sl_real = price + sl_pips
        tp_real = price - (sl_pips * 2.5)

    active_trades[symbol] = {
        'type': action,
        'entry': price,
        'sl': sl_real,
        'tp': tp_real,
        'start_time': datetime.now()
    }
    
    print(f"🚀 OPEN {action} {symbol} @ {price}")
    msg = (
        f"⚡ <b>SIGNAL ENTRY ({symbol})</b>\n"
        f"Action: <b>{action}</b>\n"
        f"Price: {price}\n"
        f"RSI: {rsi:.1f} (Valid)\n"
        f"🎯 TP: {tp_real:.4f}\n"
        f"🛑 SL: {sl_real:.4f}"
    )
    send_telegram(msg)

def check_exit(symbol, current_price):
    trade = active_trades.get(symbol)
    if not trade: return

    reason = ""
    pnl_raw = 0
    
    # Logic Exit
    if trade['type'] == 'LONG':
        if current_price >= trade['tp']:
            reason = "✅ TAKE PROFIT"
            pnl_raw = (trade['tp'] - trade['entry']) / trade['entry']
        elif current_price <= trade['sl']:
            reason = "❌ STOP LOSS"
            pnl_raw = (trade['sl'] - trade['entry']) / trade['entry']
            
    elif trade['type'] == 'SHORT':
        if current_price <= trade['tp']:
            reason = "✅ TAKE PROFIT"
            pnl_raw = (trade['entry'] - trade['tp']) / trade['entry']
        elif current_price >= trade['sl']:
            reason = "❌ STOP LOSS"
            pnl_raw = (trade['entry'] - trade['sl']) / trade['entry']

    if reason:
        pnl_pct = pnl_raw * 100 * LEVERAGE
        print(f"EXIT {symbol}: {reason}")
        msg = (
            f"🏁 <b>CLOSE POSITION ({symbol})</b>\n"
            f"Status: <b>{reason}</b>\n"
            f"Price: {current_price}\n"
            f"PnL: {pnl_pct:.2f}% (Lev {LEVERAGE}x)"
        )
        send_telegram(msg)
        del active_trades[symbol]

def run_bot():
    send_telegram("🤖 <b>Bot Futures V2 (Aggressive) Aktif</b>\nStrategy: EMA 7/14 + RSI Filter")
    
    while True:
        print(f"\n[{datetime.now().strftime('%H:%M')}] Scanning Market...", flush=True)
        
        for symbol in SYMBOLS:
            df = get_data(symbol)
            if df is None: continue
            
            last = df.iloc[-1]
            prev = df.iloc[-2]
            current_price = last['close']
            
            # Cek Posisi Existing
            if symbol in active_trades:
                check_exit(symbol, current_price)
            else:
                # --- STRATEGI BARU ---
                
                # 1. Golden Cross (Fast EMA cross Slow EMA)
                cross_up = prev['EMA_FAST'] < prev['EMA_SLOW'] and last['EMA_FAST'] > last['EMA_SLOW']
                cross_down = prev['EMA_FAST'] > prev['EMA_SLOW'] and last['EMA_FAST'] < last['EMA_SLOW']
                
                # 2. Trend Filter (Price vs EMA 200)
                is_uptrend = last['close'] > last['EMA_TREND']
                is_downtrend = last['close'] < last['EMA_TREND']
                
                # 3. RSI Filter (Jangan Beli di Pucuk)
                rsi_safe_buy = last['RSI'] < 70  # Masih ada ruang naik
                rsi_safe_sell = last['RSI'] > 30 # Masih ada ruang turun
                
                # EKSEKUSI
                if cross_up and is_uptrend and rsi_safe_buy:
                    open_position(symbol, 'LONG', current_price, last['ATR'], last['RSI'])
                    
                elif cross_down and is_downtrend and rsi_safe_sell:
                    open_position(symbol, 'SHORT', current_price, last['ATR'], last['RSI'])
            
            time.sleep(1) # Anti-ban delay
            
        time.sleep(60)

if __name__ == "__main__":
    run_bot()
