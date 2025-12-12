# Gunakan Python 3.12-slim
FROM python:3.12-slim

# Set Timezone Jakarta
ENV TZ=Asia/Jakarta
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Log Real-time
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install Compiler (Wajib untuk build library berat)
RUN apt-get update && \
    apt-get install -y gcc python3-dev libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY . .

# Upgrade pip
RUN pip install --upgrade pip

# Install library
RUN pip install -r requirements.txt

CMD ["python", "bot.py"]
