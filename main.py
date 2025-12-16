import ccxt
import pandas as pd
import time
import os
import requests
import sys
import math
from datetime import datetime

# --- KONFIGURASI LIVE ---
API_KEY = os.getenv("BINANCE_API_KEY")
SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- SETTING KHUSUS MODAL KECIL (RP 250.000 / $15.5) ---
TRADE_SIZE_USDT = 5.0   # Hanya pakai $5 per posisi (Rp 80rb-an)
LEVERAGE = 10           # Leverage 10x (Wajib, biar memenuhi syarat min order Binance)
MAX_OPEN_POSITIONS = 2  # Maksimal pegang 2 koin saja (Jaga margin aman)

TIMEFRAME = '1h'

# Global Memory
active_trades = {}     
current_symbols = []   

print(f"--- STARTING LIVE BOT (MICRO ACCOUNT MODE) ---")

# Inisialisasi Koneksi Binance
try:
    exchange = ccxt.binance({
        'apiKey': API_KEY,
        'secret': SECRET_KEY,
        'options': {'defaultType': 'future'},
        'enableRateLimit': True
    })
    # Cek saldo
    balance = exchange.fetch_balance()
    usdt_free = balance['USDT']['free']
    print(f"✅ Login Sukses. Saldo: ${usdt_free:.2f}")
    
    if usdt_free < 10:
        print("⚠️ PERINGATAN: Saldo sangat mepet (< $10). Bot mungkin gagal order.")
        
except Exception as e:
    print(f"❌ Gagal Login Binance: {e}")
    sys.exit(1)

def send_telegram(msg):
    if not TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try: requests.post(url, data=data, timeout=10)
    except: pass

# --- SMART SCANNER (Cari Koin Ramai) ---
def scan_top_coins():
    try:
        tickers = exchange.fetch_tickers()
        valid_tickers = [d for s, d in tickers.items() if '/USDT' in s and d['quoteVolume']]
        sorted_tickers = sorted(valid_tickers, key=lambda x: x['quoteVolume'], reverse=True)
        
        top_coins = []
        for t in sorted_tickers:
            sym = t['symbol']
            # Hindari Stablecoin
            if any(x in sym for x in ['USDC', 'BUSD', 'USDP', 'FDUSD', 'TUSD']): continue
            top_coins.append(sym)
            if len(top_coins) >= 15: break # Pantau Top 15
        return top_coins
    except: return []

# --- SYNC POSISI SAAT RESTART ---
def sync_existing_positions():
    print("🔄 Cek Posisi Aktif di Binance...")
    try:
        positions = exchange.fetch_positions()
        count = 0
        for pos in positions:
            if float(pos['contracts']) > 0:
                symbol = pos['symbol']
                side = 'LONG' if pos['side'] == 'long' else 'SHORT'
                entry = float(pos['entryPrice'])
                
                # Set TP/SL Darurat jika restart
                if side == 'LONG':
                    tp = entry * 1.04 # TP 4%
                    sl = entry * 0.98 # SL 2%
                else:
                    tp = entry * 0.96
                    sl = entry * 1.02
                
                active_trades[symbol] = {'type': side, 'entry': entry, 'tp': tp, 'sl': sl}
                count += 1
        print(f"✅ Ditemukan {count} posisi berjalan.")
    except Exception as e:
        print(f"⚠️ Gagal Sync: {e}")

# --- EKSEKUSI ORDER ---
def execute_order(symbol, side, price):
    try:
        # 1. Set Leverage
        try: exchange.set_leverage(LEVERAGE, symbol)
        except: pass 

        # 2. Hitung Size
        # Modal $5 x Leverage 10 = Order Size $50 (Aman, diatas min $5)
        amount_raw = (TRADE_SIZE_USDT * LEVERAGE) / price
        amount = exchange.amount_to_precision(symbol, amount_raw)
        
        # 3. Order
        order_type = 'buy' if side == 'LONG' else 'sell'
        exchange.create_market_order(symbol, order_type, amount)
        
        print(f"✅ SUCCESS {side} {symbol}")
        return True
    except Exception as e:
        print(f"❌ Gagal Order {symbol}: {e}")
        # Kirim notif error biar tau kalau saldo kurang/error lain
        send_telegram(f"⚠️ <b>GAGAL ORDER {symbol}</b>\nMsg: {e}")
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
            print(f"✅ CLOSED {symbol}")
            return True
    except Exception as e:
        print(f"❌ Gagal Close {symbol}: {e}")
        return False

# --- LOGIKA EMA AGGRESSIVE ---
def calculate_indicators(df):
    df['EMA_FAST'] = df['close'].ewm(span=7, adjust=False).mean()
    df['EMA_SLOW'] = df['close'].ewm(span=14, adjust=False).mean()
    df['EMA_TREND'] = df['close'].ewm(span=200, adjust=False).mean()
    
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
    loss = -delta.where(delta < 0, 0).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    df['tr'] = df[['high', 'low', 'close']].apply(lambda x: max(x['high']-x['low'], abs(x['high']-x['close']), abs(x['low']-x['close'])), axis=1)
    df['ATR'] = df['tr'].rolling(window=14).mean()
    return df

def get_data(symbol):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=205)
        df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
        return calculate_indicators(df)
    except: return None

def check_market(symbol):
    df = get_data(symbol)
    if df is None: return
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    price = last['close']
    
    # 1. CEK EXIT
    if symbol in active_trades:
        trade = active_trades[symbol]
        reason = ""
        pnl = 0
        
        if trade['type'] == 'LONG':
            if price >= trade['tp']: reason = "✅ TAKE PROFIT"
            elif price <= trade['sl']: reason = "❌ STOP LOSS"
        elif trade['type'] == 'SHORT':
            if price <= trade['tp']: reason = "✅ TAKE PROFIT"
            elif price >= trade['sl']: reason = "❌ STOP LOSS"
            
        if reason:
            success = close_position_real(symbol, trade['type'])
            if success:
                if trade['type'] == 'LONG': pnl = (price - trade['entry']) / trade['entry'] * 100 * LEVERAGE
                else: pnl = (trade['entry'] - price) / trade['entry'] * 100 * LEVERAGE
                send_telegram(f"💰 <b>REALIZED PnL ({symbol})</b>\nStatus: {reason}\nResult: {pnl:.2f}% (Est)")
                del active_trades[symbol]
        return

    # 2. CEK ENTRY (Cuma boleh jika posisi < 2)
    if len(active_trades) >= MAX_OPEN_POSITIONS: return

    # Logic: Cross EMA 7/14 + Trend + RSI
    cross_up = prev['EMA_FAST'] < prev['EMA_SLOW'] and last['EMA_FAST'] > last['EMA_SLOW']
    cross_down = prev['EMA_FAST'] > prev['EMA_SLOW'] and last['EMA_FAST'] < last['EMA_SLOW']
    is_uptrend = price > last['EMA_TREND']
    is_downtrend = price < last['EMA_TREND']
    
    action = None
    if cross_up and is_uptrend and last['RSI'] < 70: action = 'LONG'
    elif cross_down and is_downtrend and last['RSI'] > 30: action = 'SHORT'
    
    if action:
        success = execute_order(symbol, action, price)
        if success:
            atr = last['ATR']
            sl_pips = atr * 1.5
            if action == 'LONG':
                sl = price - sl_pips
                tp = price + (sl_pips * 3.0)
            else:
                sl = price + sl_pips
                tp = price - (sl_pips * 3.0)
            
            active_trades[symbol] = {'type': action, 'entry': price, 'tp': tp, 'sl': sl}
            send_telegram(f"🚀 <b>OPEN {action} ({symbol})</b>\nEntry: {price}\nTP: {tp:.4f}\nSL: {sl:.4f}")

def run_bot():
    global current_symbols
    sync_existing_positions()
    
    current_symbols = scan_top_coins()
    send_telegram(f"🤖 <b>BOT LIVE (MODAL 250RB)</b>\nMargin: $5/trade\nMax Pos: 2 Trade\nScan: {len(current_symbols)} Coins")
    
    cycle = 0
    while True:
        if cycle % 60 == 0: 
            new_sym = scan_top_coins()
            if new_sym: current_symbols = new_sym
            
        print(f"[{datetime.now().strftime('%H:%M')}] Scanning {len(current_symbols)} Top Coins...", flush=True)
            
        for sym in current_symbols:
            check_market(sym)
            time.sleep(1) 
            
        time.sleep(30)
        cycle += 1

if __name__ == "__main__":
    run_bot()
