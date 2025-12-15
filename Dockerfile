FROM python:3.9-slim

WORKDIR /app

# Set Timezone Jakarta
ENV TZ=Asia/Jakarta
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Tambahkan -u agar log langsung keluar
CMD ["python", "-u", "main.py"]

