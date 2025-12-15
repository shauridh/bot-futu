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

# --- DATA LIST COIN ---
# Kita pantau 10 koin futures teramai (High Volume)
SYMBOLS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
    'DOGE/USDT', 'ADA/USDT', 'AVAX/USDT', 'LINK/USDT', 'TRX/USDT'
]

TIMEFRAME = '1h'         
LEVERAGE = 5

# --- MEMORY PENYIMPANAN STATUS (STATE MANAGEMENT) ---
# Dictionary untuk menyimpan status trading per koin
# Format: active_trades['BTC/USDT'] = {'pos': 'LONG', 'entry': 50000, 'tp': 51000, 'sl': 49000}
active_trades = {}

print(f"--- STARTING MULTI-PAIR BOT ({len(SYMBOLS)} Pairs) ---")

# Inisialisasi Exchange (Public Data)
try:
    exchange = ccxt.binance({'options': {'defaultType': 'future'}})
    exchange.load_markets() # Load market info dulu
    print("✅ Koneksi Binance OK. Market loaded.")
except Exception as e:
    print(f"❌ Gagal Init: {e}")
    sys.exit(1)

def send_telegram(msg):
    if not TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try: requests.post(url, data=data, timeout=10)
    except: pass

def calculate_indicators(df):
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # ATR Logic
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
    except Exception as e:
        print(f"⚠️ Skip {symbol}: {e}")
        return None

def open_position(symbol, action, price, atr):
    # Hitung TP/SL
    sl_pips = atr * 1.5
    
    if action == 'LONG':
        sl_real = price - sl_pips
        tp_real = price + (sl_pips * 2.0)
    else: # SHORT
        sl_real = price + sl_pips
        tp_real = price - (sl_pips * 2.0)

    # Simpan ke Memory Bot
    active_trades[symbol] = {
        'type': action,
        'entry': price,
        'sl': sl_real,
        'tp': tp_real
    }
    
    print(f"🚀 OPEN {action} {symbol} @ {price}")
    msg = (
        f"⚡ <b>SIGNAL ENTRY ({symbol})</b>\n"
        f"Action: <b>{action}</b>\n"
        f"Price: {price}\n"
        f"🎯 TP: {tp_real:.4f}\n"
        f"🛑 SL: {sl_real:.4f}\n"
        f"Volatilitas: High"
    )
    send_telegram(msg)

def check_exit(symbol, current_price):
    trade = active_trades.get(symbol)
    if not trade: return

    reason = ""
    pnl_raw = 0
    
    # Cek Kondisi Exit LONG
    if trade['type'] == 'LONG':
        if current_price >= trade['tp']:
            reason = "✅ TAKE PROFIT"
            pnl_raw = (trade['tp'] - trade['entry']) / trade['entry']
        elif current_price <= trade['sl']:
            reason = "❌ STOP LOSS"
            pnl_raw = (trade['sl'] - trade['entry']) / trade['entry']
            
    # Cek Kondisi Exit SHORT
    elif trade['type'] == 'SHORT':
        if current_price <= trade['tp']:
            reason = "✅ TAKE PROFIT"
            pnl_raw = (trade['entry'] - trade['tp']) / trade['entry']
        elif current_price >= trade['sl']:
            reason = "❌ STOP LOSS"
            pnl_raw = (trade['entry'] - trade['sl']) / trade['entry']

    # Jika Exit Triggered
    if reason:
        pnl_pct = pnl_raw * 100 * LEVERAGE
        print(f"EXIT {symbol}: {reason}")
        
        msg = (
            f"🏁 <b>CLOSE POSITION ({symbol})</b>\n"
            f"Status: <b>{reason}</b>\n"
            f"Exit Price: {current_price}\n"
            f"PnL (Lev {LEVERAGE}x): {pnl_pct:.2f}%"
        )
        send_telegram(msg)
        
        # Hapus dari memory
        del active_trades[symbol]

def run_bot():
    send_telegram(f"🤖 <b>Multi-Pair Bot Aktif!</b>\nMemantau: {len(SYMBOLS)} Pairs\nMode: Paper Trading")
    
    while True:
        print(f"\n[{datetime.now().strftime('%H:%M')}] Scanning {len(SYMBOLS)} coins...", flush=True)
        
        for symbol in SYMBOLS:
            # 1. Ambil Data
            df = get_data(symbol)
            if df is None: continue # Skip jika error ambil data
            
            last = df.iloc[-1]
            prev = df.iloc[-2]
            current_price = last['close']
            
            # 2. Cek apakah koin ini sedang punya posisi?
            if symbol in active_trades:
                # Kalau punya posisi, cek apakah harus TP/SL
                check_exit(symbol, current_price)
            else:
                # Kalau kosong, cari sinyal Entry baru
                cross_up = prev['EMA_9'] < prev['EMA_21'] and last['EMA_9'] > last['EMA_21']
                trend_up = last['close'] > last['EMA_200']
                
                cross_down = prev['EMA_9'] > prev['EMA_21'] and last['EMA_9'] < last['EMA_21']
                trend_down = last['close'] < last['EMA_200']
                
                if cross_up and trend_up:
                    open_position(symbol, 'LONG', current_price, last['ATR'])
                elif cross_down and trend_down:
                    open_position(symbol, 'SHORT', current_price, last['ATR'])
            
            # Jeda kecil antar koin biar IP tidak diblokir Binance
            time.sleep(1) 
            
        print("...Scan Selesai. Tidur 60 detik.", flush=True)
        time.sleep(60)

if __name__ == "__main__":
    run_bot()
