import pandas as pd
import pandas_ta as ta
import time

def main():
    print("Bot dimulai...")
    
    # 1. Contoh Data Dummy
    df = pd.DataFrame({
        'open': [100, 102, 104, 103, 105, 107, 106, 108, 110, 112],
        'high': [105, 106, 108, 107, 109, 111, 110, 112, 115, 116],
        'low':  [95, 98, 100, 99, 101, 103, 102, 104, 106, 108],
        'close': [102, 104, 103, 105, 107, 106, 108, 110, 112, 114],
        'volume': [100, 100, 100, 100, 100, 100, 100, 100, 100, 100]
    })

    # 2. Hitung Supertrend (Versi Development sudah support 'append=True' tanpa error)
    # length=10, multiplier=3 adalah settingan standar supertrend
    df.ta.supertrend(length=10, multiplier=3, append=True)
    
    # 3. Cek Hasil
    print("Indikator berhasil dihitung. 5 Data terakhir:")
    print(df.tail())

if __name__ == "__main__":
    while True:
        main()
        time.sleep(60)
