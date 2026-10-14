# Typhoon OCR API

API สำหรับทำ OCR เอกสารภาษาไทย (รูปภาพ + PDF) ด้วย **Typhoon OCR 1.5 (ผ่าน typhoon-ocr)** บน **FastAPI**  
ต่อกับ **Ollama ที่รันใน Docker** และมีการเก็บเวลาใช้งานแต่ละคำขอเพื่อดู performance ได้

## Overview

โปรเจกต์นี้คือ REST API ตัวกลาง ที่ทำหน้าที่:

- รับไฟล์จาก HTTP (`multipart/form-data`)
- แปลง PDF เป็นภาพด้วย **PyMuPDF**
- ส่งภาพไปให้ `typhoon_ocr.ocr_document` (ซึ่งไปเรียก Typhoon OCR ผ่าน Ollama `/v1/chat/completions`)
- ส่งคืนผล OCR เป็น JSON  
เน้นใช้งานง่ายและเอาไปต่อกับระบบอื่น เช่น n8n / workflow automation / internal tools



## Tech Stack

- **Language**: Python 3.11
- **Web Framework**: FastAPI
- **ASGI Server**: Uvicorn
- **OCR Wrapper**: `typhoon-ocr` (เรียก Typhoon OCR 1.5)
- **PDF Engine**: PyMuPDF (`fitz`)
- **Container**: Docker
- **LLM Backend**: Ollama (รัน Typhoon OCR model ใน Docker)



## Requirements

- Python 3.11+ (สำหรับรันแบบ local)
- Docker (ใช้รัน Ollama และ/หรือ API)
- Ollama image: `ollama/ollama`
- โมเดลใน Ollama: `scb10x/typhoon-ocr1.5-3b`

ตัวอย่างการเตรียมโมเดลใน Ollama container:

```bash
docker exec -it ollama bash
ollama pull scb10x/typhoon-ocr1.5-3b
exit
```

## Folder Structure
```bash
typhoon_ocr_api/
  ├─ main.py              # FastAPI app (ocr_image + ocr_pdf)
  ├─ requirements.txt     # Python dependencies
  ├─ Dockerfile           # Build Typhoon OCR API image
  ├─ .dockerignore        # Exclude venv / cache จาก Docker context
  └─ README.md            # ไฟล์นี้
```



## Environment Variables

ใน main.py ใช้ค่าเริ่มต้นดังนี้:
```bash
TYPHOON_BASE_URL = os.getenv("TYPHOON_BASE_URL", "http://localhost:11434/v1")
TYPHOON_API_KEY   = os.getenv("TYPHOON_API_KEY", "ollama")
TYPHOON_MODEL     = os.getenv("TY_OCR_MODEL", "scb10x/typhoon-ocr1.5-3b")

MAX_PAGES_HARD_LIMIT = int(os.getenv("MAX_PAGES_HARD_LIMIT", "100"))
OCR_MAX_PARALLEL     = int(os.getenv("OCR_MAX_PARALLEL", "2"))
MAX_UPLOAD_SIZE_MB   = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))
```
ใช้จริง (กรณี Ollama รันใน Docker และเปิดพอร์ต 11434 ออกมา):

## กรณี API รันบน host (local Python) + Ollama อยู่ใน Docker
```bash
TYPHOON_BASE_URL=http://localhost:11434/v1
TYPHOON_API_KEY=ollama
TY_OCR_MODEL=scb10x/typhoon-ocr1.5-3b

MAX_PAGES_HARD_LIMIT=100
OCR_MAX_PARALLEL=2
MAX_UPLOAD_SIZE_MB=50
```

## กรณี API รันใน Docker + Ollama รันใน Docker (แยก container)
ถ้า Ollama container เปิดพอร์ต 11434 มาที่ host แล้วใช้:
```bash
docker run -d \
  --name Typhoon-Ocr-Api \
  -p 8000:8000 \
  -e TYPHOON_BASE_URL=http://host.docker.internal:11434/v1 \
  -e TYPHOON_API_KEY=ollama \
  -e TY_OCR_MODEL=scb10x/typhoon-ocr1.5-3b \
  -e MAX_PAGES_HARD_LIMIT=100 \
  -e OCR_MAX_PARALLEL=2 \
  -e MAX_UPLOAD_SIZE_MB=50 \
  typhoon-ocr-api:latest

```  


## Installation & Run (Local)
## 1. เตรียม Python environment
```bash

cd typhoon_ocr_api

python -m venv venv
# Windows PowerShell
.\venv\Scripts\activate

pip install -r requirements.txt
```

## 2. ให้ Ollama (ใน Docker) รันอยู่และเปิดพอร์ต 11434

ตัวอย่าง:
```bash
docker run -d \
  --name ollama \
  -p 11434:11434 \
  ollama/ollama
```
แล้วเข้าไป pull โมเดล (ถ้ายังไม่ได้ดึงมาก่อน):
```bash

docker exec -it ollama bash
ollama pull scb10x/typhoon-ocr1.5-3b
exit

```

## 3. ตั้งค่า environment (ถ้าจำเป็น)
```bash

set TYPHOON_BASE_URL=http://localhost:11434/v1
set TYPHOON_API_KEY=ollama
set TY_OCR_MODEL=scb10x/typhoon-ocr1.5-3b
```

## 4. รัน API
```bash

uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## เปิดดู docs:
```bash

http://localhost:8000/docs
```

## Installation & Run (Docker สำหรับ API)

## 1. Build image
```bash

cd typhoon_ocr_api
docker build -t typhoon-ocr-api .
```
ต้องมี requirements.txt, main.py และ Dockerfile อยู่ในโฟลเดอร์

## 2. รัน container (เชื่อมกับ Ollama container)
ตัวอย่าง (Ollama container เปิดพอร์ต 11434 Mapping ออกมาแล้ว):
```bash

docker run -d \
  --name Typhoon-Ocr-Api \
  -p 8000:8000 \
  -e TYPHOON_BASE_URL=http://host.docker.internal:11434/v1 \
  -e TYPHOON_API_KEY=ollama \
  -e TY_OCR_MODEL=scb10x/typhoon-ocr1.5-3b \
  -e MAX_PAGES_HARD_LIMIT=100 \
  -e OCR_MAX_PARALLEL=2 \
  -e MAX_UPLOAD_SIZE_MB=50 \
  typhoon-ocr-api:latest
```
จากนั้นเปิด:
```bash

http://localhost:8000/docs
```


## API Endpoints
## 1. ```POST /ocr_image```
- OCR รูปภาพเดี่ยวด้วย Typhoon OCR

- Content-Type: ```multipart/form-data```

- Field: ```file``` (image/jpeg, image/png ฯลฯ)

ตัวอย่าง cURL
```bash
curl -X POST "http://localhost:8000/ocr_image" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@test.jpg;type=image/jpeg"
```
ตัวอย่าง Response
```bash

{
  "status": "ok",
  "filename": "test.jpg",
  "mime_type": "image/jpeg",
  "ocr": "ข้อความที่อ่านได้จาก Typhoon-OCR ...",
  "processing_seconds": 2.734
}
```

## 2. ```POST /ocr_pdf```
- OCR PDF หลายหน้า:
- ตรวจว่าเป็น PDF จริง (เช็ค %PDF)
- จำกัดขนาดไฟล์ด้วย MAX_UPLOAD_SIZE_MB
- จำกัดจำนวนหน้าด้วย MAX_PAGES_HARD_LIMIT
- ใช้ PyMuPDF render หน้า → PNG แล้ว OCR แบบ parallel

Query parameters
| ชื่อ         | ค่า default | อธิบาย                           |
| ------------ | ----------: | -------------------------------- |
| `start_page` |         `1` | หน้าเริ่มต้น (1-based)           |
| `end_page`   |      `None` | ถ้าไม่ระบุ จะไปจนถึงหน้าสุดท้าย  |
| `max_pages`  |        `20` | สูงสุดกี่หน้าที่จะ OCR ในคำขอนี้ |
| `dpi`        |       `200` | DPI ตอน render PDF → PNG         |

ตัวอย่าง cURL
```
curl -X POST \
  "http://localhost:8000/ocr_pdf?start_page=1&max_pages=20&dpi=200" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@คำฟ้อง 10.pdf;type=application/pdf"
```
ตัวอย่างโครงสร้าง Response
```
{
  "status": "ok",
  "filename": "คำฟ้อง 10.pdf",
  "total_pages_in_pdf": 4,
  "start_page": 1,
  "end_page": 4,
  "processed_pages": 4,
  "dpi": 200,
  "pages": [
    {
      "page": 1,
      "ocr": "ข้อความหน้า 1 ...",
      "ocr_seconds": 1.234
    },
    {
      "page": 2,
      "ocr": "ข้อความหน้า 2 ...",
      "ocr_seconds": 1.567
    }
  ],
  "full_text": "ข้อความรวมทุกหน้า ...",
  "metrics": {
    "processing_seconds_total": 6.432,
    "ocr_wall_seconds": 3.210,
    "ocr_seconds_sum": 5.890,
    "ocr_seconds_avg_per_page": 1.473
  }
}
```

## Note
- ถ้า Ollama ไม่รัน หรือ ```TYPHOON_BASE_URL``` ชี้ผิด จะเกิด error จาก ```typhoon_ocr```                                                                       (เช่น connection error)

- ถ้าไฟล์ใหญ่เกิน ```MAX_UPLOAD_SIZE_MB``` จะได้ HTTP 413

- ถ้า PDF ไม่มีหน้า หรือขอหน้าเกินจำนวนหน้าจริง ระบบจะส่ง HTTP 400 กลับไปพร้อมข้อความอธิบาย
