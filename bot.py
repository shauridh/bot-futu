import ccxt
import pandas as pd
import time
import os
import requests
from datetime import datetime

# --- KONFIGURASI ---
API_KEY = os.getenv("BINANCE_API_KEY", "ISI_TESTNET_KEY")
SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "ISI_TESTNET_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- SETTING TRADING ---
SYMBOL = 'BTC/USDT'      # Kita fokus 1 pair dulu biar stabil
TIMEFRAME = '1h'         # Timeframe 1 Jam (Swing Santai)
LEVERAGE = 5             # Leverage 5x (Sesuai Request)
BALANCE_PCT = 0.5        # Pakai 50% saldo available per trade
TP_RATIO = 2.0           # Reward 2x lipat dari Risk

# Inisialisasi Exchange (TESTNET MODE)
exchange = ccxt.binance({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'options': {'defaultType': 'future'} # Wajib untuk Futures
})
exchange.set_sandbox_mode(True) # AKTIFKAN MODE TESTNET (UANG MAINAN)

def send_telegram(msg):
    if not TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try: requests.post(url, data=data, timeout=10)
    except: pass

# --- INDIKATOR MANUAL (PURE PANDAS) ---
def calculate_indicators(df):
    # EMA 9, 21, 200
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # ATR 14 (Volatilitas)
    df['tr1'] = df['high'] - df['low']
    df['tr2'] = abs(df['high'] - df['close'].shift())
    df['tr3'] = abs(df['low'] - df['close'].shift())
    df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
    df['ATR'] = df['tr'].rolling(window=14).mean()
    
    return df

def get_data():
    try:
        bars = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=250)
        df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        return calculate_indicators(df)
    except Exception as e:
        print(f"Error fetch data: {e}")
        return None

def get_position():
    try:
        balance = exchange.fetch_balance()
        positions = balance['info']['positions']
        for p in positions:
            if p['symbol'] == SYMBOL.replace('/', ''): # BTCUSDT
                amt = float(p['positionAmt'])
                return amt # Positif = Long, Negatif = Short, 0 = No Position
        return 0.0
    except Exception as e:
        print(f"Error check position: {e}")
        return 0.0

def execute_trade(signal, price, atr):
    try:
        # 1. Hitung Quantity
        balance = exchange.fetch_balance()['USDT']['free']
        risk_amount = balance * BALANCE_PCT * LEVERAGE
        amount = risk_amount / price
        
        # 2. Hitung TP/SL Dinamis
        sl_pips = atr * 1.5 # Stop Loss = 1.5x ATR
        
        if signal == 'LONG':
            sl_price = price - sl_pips
            tp_price = price + (sl_pips * TP_RATIO)
            side = 'buy'
        else: # SHORT
            sl_price = price + sl_pips
            tp_price = price - (sl_pips * TP_RATIO)
            side = 'sell'

        # 3. Eksekusi Order (Market)
        print(f"🚀 EXECUTING {signal}...")
        order = exchange.create_order(SYMBOL, 'market', side, amount)
        
        # 4. Pasang TP & SL (OSCO Logic sederhana)
        # Note: Di CCXT standard, kita kirim limit & stop manual
        if signal == 'LONG':
            exchange.create_order(SYMBOL, 'limit', 'sell', amount, tp_price) # TP
            exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', amount, params={'stopPrice': sl_price}) # SL
        else:
            exchange.create_order(SYMBOL, 'limit', 'buy', amount, tp_price) # TP
            exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', amount, params={'stopPrice': sl_price}) # SL
            
        msg = (
            f"🤖 <b>BINANCE TESTNET SIGNAL</b>\n"
            f"Action: <b>{signal}</b> {SYMBOL}\n"
            f"Entry: {price}\n"
            f"💰 TP: {tp_price:.2f}\n"
            f"🛑 SL: {sl_price:.2f}\n"
            f"Volatilitas (ATR): {atr:.2f}"
        )
        send_telegram(msg)
        
    except Exception as e:
        print(f"Trade Error: {e}")
        send_telegram(f"⚠️ Error Execute: {e}")

def run_bot():
    print(f"🤖 Bot Crypto {SYMBOL} Started (Testnet)...")
    send_telegram(f"🤖 <b>Bot Crypto Aktif</b>\nPair: {SYMBOL}\nMode: TESTNET (Simulasi)")
    
    # Set Leverage di Awal
    try:
        exchange.set_leverage(LEVERAGE, SYMBOL)
    except:
        pass # Kadang testnet error set leverage, ignore aja

    while True:
        try:
            df = get_data()
            if df is None: 
                time.sleep(10)
                continue
                
            last = df.iloc[-1]
            prev = df.iloc[-2]
            
            # Cek Posisi Sekarang
            pos_size = get_position()
            
            if pos_size == 0:
                # --- LOGIKA ENTRY ---
                
                # Sinyal EMA Cross UP (Long)
                # Syarat: Close > EMA 200 (Trend Bullish) DAN EMA 9 Potong EMA 21 ke atas
                cross_up = prev['EMA_9'] < prev['EMA_21'] and last['EMA_9'] > last['EMA_21']
                trend_up = last['close'] > last['EMA_200']
                
                if cross_up and trend_up:
                    execute_trade('LONG', last['close'], last['ATR'])

                # Sinyal EMA Cross DOWN (Short)
                # Syarat: Close < EMA 200 (Trend Bearish) DAN EMA 9 Potong EMA 21 ke bawah
                cross_down = prev['EMA_9'] > prev['EMA_21'] and last['EMA_9'] < last['EMA_21']
                trend_down = last['close'] < last['EMA_200']
                
                if cross_down and trend_down:
                    execute_trade('SHORT', last['close'], last['ATR'])
                    
            else:
                print(f"Posisi sedang terbuka: {pos_size}. Menunggu TP/SL...")
            
            # Tunggu 1 menit sebelum cek lagi (Looping)
            time.sleep(60) 
            
        except Exception as e:
            print(f"Loop Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_bot()
