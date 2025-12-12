# GANTI DARI: python:3.9-slim
# MENJADI: python:3.9 (Image standar yang lebih lengkap)
FROM python:3.9

# Set working directory
WORKDIR /app

# Upgrade pip terlebih dahulu untuk menghindari masalah kompatibilitas
RUN pip install --upgrade pip

# Copy requirements dan install dependencies
COPY requirements.txt .
# Hapus --no-cache-dir jika internet lambat, tapi di VPS biasanya aman
RUN pip install --no-cache-dir -r requirements.txt

# Copy seluruh kode ke dalam container
COPY . .

# Perintah untuk menjalankan bot
CMD ["python", "-u", "main.py"]
