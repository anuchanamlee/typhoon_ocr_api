# ใช้ Python 3.11 base image
FROM python:3.11

# ไม่เขียน .pyc และไม่ buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# โฟลเดอร์ทำงานใน container
WORKDIR /app

# ติดตั้ง dependency จาก requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# คัดลอกโค้ดทั้งหมดเข้า container
COPY . .

# เปิด port 8000 ใน container
EXPOSE 8000

# รัน FastAPI ด้วย uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

