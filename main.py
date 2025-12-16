import ccxt
import pandas as pd
import time
import os
import requests
import sys
from datetime import datetime

# --- KONFIGURASI PRO (HIGH WINRATE) ---
API_KEY = os.getenv("BINANCE_API_KEY")
SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- MODAL & RISIKO ---
TRADE_SIZE_USDT = 6.0   
LEVERAGE = 10           
MAX_OPEN_POSITIONS = 3  

# --- TEKNIKAL ---
# Kita butuh dua timeframe:
TF_TREND = '1h'    # Untuk melihat arah angin (Filter)
TF_ENTRY = '5m'    # Untuk eksekusi (Sniper)

TP_PERCENT = 0.013      # Target 1.3%
SL_PERCENT = 0.020      # SL 2% (Lebih longgar karena searah tren, jarang kena)

# Memory
active_trades = {}     
current_symbols = []   

print(f"--- STARTING HIGH WINRATE BOT (TREND FILTERED) ---")

try:
    exchange = ccxt.binance({
        'apiKey': API_KEY,
        'secret': SECRET_KEY,
        'options': {'defaultType': 'future'},
        'enableRateLimit': True
    })
    exchange.load_markets()
    balance = exchange.fetch_balance()
    print(f"✅ Login Sukses. Saldo Available: ${balance['USDT']['free']:.2f}")
except Exception as e:
    print(f"❌ Error Login: {e}")
    sys.exit(1)

def send_telegram(msg):
    if not TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try: requests.post(url, data=data, timeout=5)
    except: pass

def scan_top_coins():
    # Cari koin volume besar agar teknikal valid
    try:
        tickers = exchange.fetch_tickers()
        valid_tickers = [d for s, d in tickers.items() if '/USDT' in s and d['quoteVolume']]
        sorted_tickers = sorted(valid_tickers, key=lambda x: x['quoteVolume'], reverse=True)
        top_coins = []
        for t in sorted_tickers:
            sym = t['symbol']
            if any(x in sym for x in ['USDC', 'BUSD', 'FDUSD']): continue
            top_coins.append(sym)
            if len(top_coins) >= 12: break 
        return top_coins
    except: return []

def execute_order(symbol, side, price):
    try:
        try: exchange.set_leverage(LEVERAGE, symbol)
        except: pass 
        amount_raw = (TRADE_SIZE_USDT * LEVERAGE) / price
        amount = exchange.amount_to_precision(symbol, amount_raw)
        order_type = 'buy' if side == 'LONG' else 'sell'
        exchange.create_market_order(symbol, order_type, amount)
        return True
    except Exception as e:
        print(f"❌ Order Gagal {symbol}: {e}")
        return False

def close_position_real(symbol, side):
    try:
        positions = exchange.fetch_positions([symbol])
        amt = 0
        for p in positions:
            if p['symbol'] == symbol:
                amt = float(p['contracts'])
                break
        if amt > 0:
            direction = 'sell' if side == 'LONG' else 'buy'
            exchange.create_market_order(symbol, direction, amt, params={'reduceOnly': True})
            return True
    except: return False

# --- FUNGSI ANALISA UTAMA ---

def get_trend_direction(symbol):
    # Cek Tren di Timeframe 1 Jam (EMA 200)
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=TF_TREND, limit=210)
        df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
        ema200 = df['close'].ewm(span=200, adjust=False).mean().iloc[-1]
        price = df['close'].iloc[-1]
        
        if price > ema200: return 'UPTREND'
        elif price < ema200: return 'DOWNTREND'
        return 'SIDEWAYS'
    except: return 'ERROR'

def get_entry_signal(symbol):
    # Cek Sinyal di Timeframe 5 Menit (RSI + BB)
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=TF_ENTRY, limit=50)
        df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
        
        # Indikator
        df['SMA20'] = df['close'].rolling(window=20).mean()
        df['STD20'] = df['close'].rolling(window=20).std()
        df['BB_UPPER'] = df['SMA20'] + (df['STD20'] * 2)
        df['BB_LOWER'] = df['SMA20'] - (df['STD20'] * 2)
        
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
        loss = -delta.where(delta < 0, 0).ewm(alpha=1/14, adjust=False).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        last = df.iloc[-1]
        price = last['close']
        
        # Logika Reversal
        if (price < last['BB_LOWER']) and (last['RSI'] < 30): return 'BUY_SIGNAL', price, last['RSI']
        if (price > last['BB_UPPER']) and (last['RSI'] > 70): return 'SELL_SIGNAL', price, last['RSI']
        
        return None, price, 0
    except: return None, 0, 0

def check_market(symbol):
    # 1. CEK EXIT
    if symbol in active_trades:
        trade = active_trades[symbol]
        df_now = exchange.fetch_ticker(symbol)
        price = df_now['last']
        
        reason = ""
        if trade['type'] == 'LONG':
            if price >= trade['tp']: reason = "✅ TP (Win)"
            elif price <= trade['sl']: reason = "❌ SL (Loss)"
        elif trade['type'] == 'SHORT':
            if price <= trade['tp']: reason = "✅ TP (Win)"
            elif price >= trade['sl']: reason = "❌ SL (Loss)"
            
        if reason:
            if close_position_real(symbol, trade['type']):
                send_telegram(f"💰 <b>RESULT {symbol}</b>\n{reason}\nExit: {price}")
                del active_trades[symbol]
        return

    # 2. CEK ENTRY (FILTERED)
    if len(active_trades) >= MAX_OPEN_POSITIONS: return

    # Tahap A: Cek Tren Besar (1 Jam)
    major_trend = get_trend_direction(symbol)
    if major_trend == 'ERROR': return

    # Tahap B: Cek Sinyal Kecil (5 Menit)
    signal, price, rsi = get_entry_signal(symbol)
    
    action = None
    
    # KUNCI WINRATE: Hanya ambil sinyal yang SEARAH tren besar
    if signal == 'BUY_SIGNAL' and major_trend == 'UPTREND':
        action = 'LONG'
    elif signal == 'SELL_SIGNAL' and major_trend == 'DOWNTREND':
        action = 'SHORT'
    
    # Catatan: Jika Tren UPTREND tapi sinyal SELL, bot akan DIAM (Menghindari Loss)
    
    if action:
        if execute_order(symbol, action, price):
            if action == 'LONG':
                tp = price * (1 + TP_PERCENT)
                sl = price * (1 - SL_PERCENT)
            else:
                tp = price * (1 - TP_PERCENT)
                sl = price * (1 + SL_PERCENT)
            
            active_trades[symbol] = {'type': action, 'entry': price, 'tp': tp, 'sl': sl}
            send_telegram(f"🛡️ <b>FILTERED ENTRY ({symbol})</b>\nTrend 1H: {major_trend}\nAction: {action}\nPrice: {price}\nTP: {tp:.4f}")

def run_bot():
    global current_symbols
    current_symbols = scan_top_coins()
    send_telegram(f"🦅 <b>HIGH WINRATE BOT STARTED</b>\nFilter: EMA 200 (1H)\nEntry: RSI+BB (5m)\nTP: {TP_PERCENT*100}%")
    
    cycle = 0
    while True:
        if cycle % 100 == 0: 
            new = scan_top_coins()
            if new: current_symbols = new
            
        print(f"Scanning {len(current_symbols)} coins with Trend Filter...", flush=True)
        for sym in current_symbols:
            check_market(sym)
            time.sleep(1.5) # Agak santai sedikit biar API aman
            
        time.sleep(10)
        cycle += 1

if __name__ == "__main__":
    run_bot()
