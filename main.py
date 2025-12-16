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

# --- DAFTAR 45 KOIN FUTURES TERAMAI (THE LIQUID 45) ---
SYMBOLS = [
    # 1. THE KINGS
    'BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'XRP/USDT',
    
    # 2. TOP ALTS (L1)
    'ADA/USDT', 'AVAX/USDT', 'TRX/USDT', 'DOT/USDT', 'LINK/USDT',
    'MATIC/USDT', 'LTC/USDT', 'BCH/USDT', 'NEAR/USDT', 'ATOM/USDT',
    'APT/USDT', 'SUI/USDT', 'SEI/USDT', 'INJ/USDT', 'FTM/USDT',
    
    # 3. MEME COINS (High Risk High Reward)
    'DOGE/USDT', 'SHIB/USDT', 'PEPE/USDT', 'WIF/USDT', 'BONK/USDT', 'FLOKI/USDT',
    
    # 4. LAYER 2 & DEFI
    'ARB/USDT', 'OP/USDT', 'LDO/USDT', 'UNI/USDT', 'AAVE/USDT',
    'MKR/USDT', 'SNX/USDT', 'TIA/USDT', 'STRK/USDT',
    
    # 5. AI & GAMING
    'RNDR/USDT', 'FET/USDT', 'GALA/USDT', 'SAND/USDT', 'MANA/USDT',
    'IMX/USDT', 'AXS/USDT', 'GRT/USDT', 'THETA/USDT'
]

TIMEFRAME = '1h'         
LEVERAGE = 10 

# Memory Posisi
active_trades = {}

print(f"--- STARTING MEGA-BOT ({len(SYMBOLS)} Pairs) ---")

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
    # EMA Aggressive (7 & 14)
    df['EMA_FAST'] = df['close'].ewm(span=7, adjust=False).mean()
    df['EMA_SLOW'] = df['close'].ewm(span=14, adjust=False).mean()
    
    # EMA Trend Filter (200)
    df['EMA_TREND'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
    loss = -delta.where(delta < 0, 0).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # ATR
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
    # SL 1.5x ATR (Agak longgar dikit karena koin volatile)
    sl_pips = atr * 1.5
    
    if action == 'LONG':
        sl_real = price - sl_pips
        tp_real = price + (sl_pips * 3.0) # RR 1:3 (Cari untung lebar)
    else: # SHORT
        sl_real = price + sl_pips
        tp_real = price - (sl_pips * 3.0)

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
        f"RSI: {rsi:.1f}\n"
        f"🎯 TP: {tp_real:.4f}\n"
        f"🛑 SL: {sl_real:.4f}"
    )
    send_telegram(msg)

def check_exit(symbol, current_price):
    trade = active_trades.get(symbol)
    if not trade: return

    reason = ""
    pnl_raw = 0
    
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
            f"🏁 <b>CLOSE ({symbol})</b>\n"
            f"Status: <b>{reason}</b>\n"
            f"PnL: {pnl_pct:.2f}% (Lev {LEVERAGE}x)"
        )
        send_telegram(msg)
        del active_trades[symbol]

def run_bot():
    send_telegram(f"🤖 <b>Mega-Bot Aktif!</b>\nMemantau {len(SYMBOLS)} Koin Futures\nMode: Aggressive EMA 7/14")
    
    while True:
        print(f"\n[{datetime.now().strftime('%H:%M')}] Scanning {len(SYMBOLS)} Pairs...", flush=True)
        
        for symbol in SYMBOLS:
            df = get_data(symbol)
            if df is None: continue
            
            last = df.iloc[-1]
            prev = df.iloc[-2]
            current_price = last['close']
            
            if symbol in active_trades:
                check_exit(symbol, current_price)
            else:
                # STRATEGI:
                # 1. EMA Cross (7 & 14)
                # 2. Trend Filter (EMA 200)
                # 3. RSI Filter (30-70)
                
                cross_up = prev['EMA_FAST'] < prev['EMA_SLOW'] and last['EMA_FAST'] > last['EMA_SLOW']
                cross_down = prev['EMA_FAST'] > prev['EMA_SLOW'] and last['EMA_FAST'] < last['EMA_SLOW']
                
                is_uptrend = last['close'] > last['EMA_TREND']
                is_downtrend = last['close'] < last['EMA_TREND']
                
                rsi_safe_buy = last['RSI'] < 70
                rsi_safe_sell = last['RSI'] > 30
                
                if cross_up and is_uptrend and rsi_safe_buy:
                    open_position(symbol, 'LONG', current_price, last['ATR'], last['RSI'])
                    
                elif cross_down and is_downtrend and rsi_safe_sell:
                    open_position(symbol, 'SHORT', current_price, last['ATR'], last['RSI'])
            
            # Delay 1 detik per koin sangat penting agar tidak kena Banned Binance
            time.sleep(1) 
            
        print("...Cycle Selesai. Istirahat 30 detik.")
        time.sleep(30)

if __name__ == "__main__":
    run_bot()
