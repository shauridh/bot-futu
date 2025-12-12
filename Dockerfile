# Gunakan image python yang ringan
FROM python:3.10-slim

# Set folder kerja
WORKDIR /app

# --- BAGIAN PENTING ---
# Kita wajib install 'git' di level OS dulu, 
# karena requirements.txt akan mengambil library langsung dari Github.
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
# ----------------------

# Copy requirements dan install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy sisa kode (bot.py, dll)
COPY . .

# Jalankan bot (pastikan nama filenya benar bot.py)
CMD ["python", "bot.py", "-u"]
