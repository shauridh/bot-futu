import ccxt
import pandas as pd
import time
import os
import requests
import sys
import math
from datetime import datetime

# --- KONFIGURASI SCALPING ---
API_KEY = os.getenv("BINANCE_API_KEY")
SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- SETTING MODAL & RISIKO ---
TRADE_SIZE_USDT = 5.0   # Tetap $5 per trade (Aman untuk modal 250rb)
LEVERAGE = 10           # Leverage 10x
MAX_OPEN_POSITIONS = 3  # Naikkan jadi 3 posisi karena scalping perputarannya cepat

# --- SETTING TEKNIKAL SCALPING ---
TIMEFRAME = '5m'        # Main di Timeframe 5 Menit (Cepat)
TP_PERCENT = 0.015      # Target Profit 1.5% gerak harga (15% PnL)
SL_PERCENT = 0.008      # Stop Loss 0.8% gerak harga (8% PnL)

# Memory
active_trades = {}     
current_symbols = []   

print(f"--- STARTING SCALPING BOT (5 MINUTE) ---")

try:
    exchange = ccxt.binance({
        'apiKey': API_KEY,
        'secret': SECRET_KEY,
        'options': {'defaultType': 'future'},
        'enableRateLimit': True
    })
    balance = exchange.fetch_balance()
    usdt_free = balance['USDT']['free']
    print(f"✅ Login Sukses. Saldo: ${usdt_free:.2f}")
except Exception as e:
    print(f"❌ Error Login: {e}")
    sys.exit(1)

def send_telegram(msg):
    if not TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try: requests.post(url, data=data, timeout=5)
    except: pass

# --- SCANNER: Cari Koin Volatil (Banyak Gerak) ---
def scan_top_coins():
    try:
        tickers = exchange.fetch_tickers()
        # Cari koin dengan % change terbesar (Volatil) dalam 24 jam terakhir
        # Scalper suka koin yang 'liar' bukan yang diam
        valid_tickers = [d for s, d in tickers.items() if '/USDT' in s and d['quoteVolume']]
        
        # Sortir berdasarkan Quote Volume (Likuiditas) agar mudah jual/beli
        sorted_tickers = sorted(valid_tickers, key=lambda x: x['quoteVolume'], reverse=True)
        
        top_coins = []
        for t in sorted_tickers:
            sym = t['symbol']
            if any(x in sym for x in ['USDC', 'BUSD', 'USDP', 'FDUSD', 'TUSD']): continue
            top_coins.append(sym)
            if len(top_coins) >= 12: break # Pantau 12 Koin Teramai
        return top_coins
    except: return []

def sync_existing_positions():
    print("🔄 Sync Posisi Scalping...")
    try:
        positions = exchange.fetch_positions()
        for pos in positions:
            if float(pos['contracts']) > 0:
                symbol = pos['symbol']
                side = 'LONG' if pos['side'] == 'long' else 'SHORT'
                entry = float(pos['entryPrice'])
                
                # Set TP/SL Default Scalping jika restart
                if side == 'LONG':
                    tp = entry * (1 + TP_PERCENT)
                    sl = entry * (1 - SL_PERCENT)
                else:
                    tp = entry * (1 - TP_PERCENT)
                    sl = entry * (1 + SL_PERCENT)
                
                active_trades[symbol] = {'type': side, 'entry': entry, 'tp': tp, 'sl': sl}
    except: pass

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

# --- INDIKATOR CEPAT (EMA 5/12) ---
def calculate_indicators(df):
    # EMA Sangat Pendek untuk 5 Menit
    df['EMA_FAST'] = df['close'].ewm(span=5, adjust=False).mean()
    df['EMA_SLOW'] = df['close'].ewm(span=12, adjust=False).mean()
    
    # Trend Filter (EMA 200 di 5m) - Pastikan searah tren besar
    df['EMA_TREND'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # RSI Standard
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
    loss = -delta.where(delta < 0, 0).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    return df

def get_data(symbol):
    try:
        # Ambil data lebih sedikit biar ringan (100 candle 5 menit)
        bars = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=100)
        df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
        return calculate_indicators(df)
    except: return None

def check_market(symbol):
    df = get_data(symbol)
    if df is None: return
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    price = last['close']
    
    # 1. CEK EXIT (TP/SL)
    if symbol in active_trades:
        trade = active_trades[symbol]
        reason = ""
        
        # Logika Exit Keras (Hitung Manual)
        if trade['type'] == 'LONG':
            if price >= trade['tp']: reason = "✅ TP (Scalp)"
            elif price <= trade['sl']: reason = "❌ SL (Scalp)"
        elif trade['type'] == 'SHORT':
            if price <= trade['tp']: reason = "✅ TP (Scalp)"
            elif price >= trade['sl']: reason = "❌ SL (Scalp)"
            
        if reason:
            if close_position_real(symbol, trade['type']):
                pnl = (TP_PERCENT * 100 * LEVERAGE) if "TP" in reason else (-SL_PERCENT * 100 * LEVERAGE)
                send_telegram(f"⚡ <b>CLOSE {symbol}</b>\n{reason}\nResult: {pnl:.1f}% (Est)")
                del active_trades[symbol]
        return

    # 2. CEK ENTRY
    if len(active_trades) >= MAX_OPEN_POSITIONS: return

    # LOGIKA ENTRY SCALPING 5 MENIT:
    # 1. Cross EMA 5 & 12 (Sangat Cepat)
    # 2. RSI tidak Overbought/Oversold (Masih ada nafas)
    
    cross_up = prev['EMA_FAST'] < prev['EMA_SLOW'] and last['EMA_FAST'] > last['EMA_SLOW']
    cross_down = prev['EMA_FAST'] > prev['EMA_SLOW'] and last['EMA_FAST'] < last['EMA_SLOW']
    
    # Filter Trend (Opsional, matikan jika ingin counter-trend. Tapi aman dinyalakan)
    is_uptrend = price > last['EMA_TREND']
    is_downtrend = price < last['EMA_TREND']
    
    action = None
    if cross_up and is_uptrend and last['RSI'] < 70: action = 'LONG'
    elif cross_down and is_downtrend and last['RSI'] > 30: action = 'SHORT'
    
    if action:
        if execute_order(symbol, action, price):
            # Hitung TP/SL Fixed
            if action == 'LONG':
                tp = price * (1 + TP_PERCENT)
                sl = price * (1 - SL_PERCENT)
            else:
                tp = price * (1 - TP_PERCENT)
                sl = price * (1 + SL_PERCENT)
            
            active_trades[symbol] = {'type': action, 'entry': price, 'tp': tp, 'sl': sl}
            send_telegram(f"🔫 <b>SCALP {action} ({symbol})</b>\nPrice: {price}\nTP: {tp:.5f}\nSL: {sl:.5f}")

def run_bot():
    global current_symbols
    sync_existing_positions()
    current_symbols = scan_top_coins()
    
    send_telegram(f"🏎️ <b>SCALPING BOT STARTED</b>\nTF: 5 Min | EMA 5/12\nTP: {TP_PERCENT*100}% | SL: {SL_PERCENT*100}%\nMax Pos: 3")
    
    cycle = 0
    while True:
        # Update list koin tiap 30 menit (Scalping butuh data segar)
        if cycle % 30 == 0: 
            new = scan_top_coins()
            if new: current_symbols = new
            
        print(f"[{datetime.now().strftime('%H:%M')}] Scalping {len(current_symbols)} Coins...", flush=True)
            
        for sym in current_symbols:
            check_market(sym)
            time.sleep(1) # Jeda 1 detik
            
        time.sleep(10) # Jeda antar cycle cuma 10 detik (Scalping harus cepat)
        cycle += 1

if __name__ == "__main__":
    run_bot()
