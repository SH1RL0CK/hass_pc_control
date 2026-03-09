FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY grub_boot_selector.py .

RUN mkdir -p /tftp

# TFTP uses UDP port 69
EXPOSE 69/udp

CMD ["python", "grub_boot_selector.py"]
