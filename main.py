import os
import asyncio
import tempfile
import time
from typing import Optional, List, Dict

import fitz  # PyMuPDF
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from typhoon_ocr import ocr_document  # ใช้ lib โดยตรง

app = FastAPI()

# ===== CONFIG =====
TYPHOON_BASE_URL = os.getenv("TYPHOON_BASE_URL", "http://localhost:11434/v1")
TYPHOON_API_KEY = os.getenv("TYPHOON_API_KEY", "ollama")
TYPHOON_MODEL = os.getenv("TY_OCR_MODEL", "scb10x/typhoon-ocr1.5-3b")

MAX_PAGES_HARD_LIMIT = int(os.getenv("MAX_PAGES_HARD_LIMIT", "100"))
OCR_MAX_PARALLEL = int(os.getenv("OCR_MAX_PARALLEL", "2"))
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))  # limit upload size for safety

_ocr_semaphore = asyncio.Semaphore(OCR_MAX_PARALLEL)


def _validate_upload_size(data: bytes, filename: str) -> None:
    """ป้องกันอัปโหลดไฟล์ใหญ่เกินไปที่อาจกิน RAM/CPU"""
    max_bytes = MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"ไฟล์ {filename!r} มีขนาดเกิน {MAX_UPLOAD_SIZE_MB}MB",
        )


async def ocr_image_bytes(img_bytes: bytes, suffix: str = ".png") -> str:
    """
    รับ bytes ของรูป/หน้า PDF แล้ว:
    1) เขียนเป็นไฟล์ชั่วคราว (เช่น .png)
    2) เรียก typhoon_ocr.ocr_document(pdf_or_image_path=...)
    3) ลบไฟล์ชั่วคราวทิ้ง
    ทำงานใน thread แยก + จำกัด parallel ด้วย semaphore
    """
    async with _ocr_semaphore:
        def _run() -> str:
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(img_bytes)
                    tmp_path = tmp.name

                markdown = ocr_document(
                    pdf_or_image_path=tmp_path,
                    base_url=TYPHOON_BASE_URL,
                    api_key=TYPHOON_API_KEY,
                    model=TYPHOON_MODEL,
                )
                return markdown
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

        return await asyncio.to_thread(_run)


# ===== ENDPOINT: OCR IMAGE =====
@app.post("/ocr_image")
async def ocr_image(
    file: UploadFile = File(...),
):
    """
    OCR ภาพเดี่ยว (JPG / PNG ฯลฯ) ด้วย typhoon_ocr.ocr_document
    """
    mime_type = file.content_type or "application/octet-stream"
    if not mime_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail=f"รองรับเฉพาะไฟล์รูปภาพเท่านั้น (ได้รับ: {mime_type})",
        )

    img_bytes = await file.read()
    if not img_bytes:
        raise HTTPException(status_code=400, detail="ไฟล์ว่างเปล่า")

    _validate_upload_size(img_bytes, file.filename or "unknown")

    # ใช้นามสกุลตามไฟล์จริง ถ้าไม่มีให้ default เป็น .png
    _, ext = os.path.splitext(file.filename or "")
    suffix = ext if ext else ".png"

    start_time = time.perf_counter()
    text = await ocr_image_bytes(img_bytes, suffix=suffix)
    duration = time.perf_counter() - start_time

    return {
        "status": "ok",
        "filename": file.filename,
        "mime_type": mime_type,
        "ocr": text,
        "processing_seconds": round(duration, 3),
    }


# ===== helper: render PDF pages to PNG bytes (run in thread) =====
def _pdf_to_images(
    pdf_bytes: bytes,
    start_page: int,
    effective_end_page: int,
    dpi: int,
) -> Dict[str, List]:
    """
    ทำงานฝั่ง blocking (ใช้กับ asyncio.to_thread):
    - เปิด PDF ด้วย PyMuPDF
    - render หน้า start_page..effective_end_page เป็น PNG bytes
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        total_pages = len(doc)
        if total_pages == 0:
            raise ValueError("PDF ไม่มีหน้า")

        if start_page > total_pages:
            raise ValueError(f"PDF มี {total_pages} หน้า แต่คุณขอเริ่มจากหน้า {start_page}")

        # 👇 สำคัญ: บีบ end_page ไม่ให้เกินจำนวนหน้าจริง
        if effective_end_page > total_pages:
            effective_end_page = total_pages

        if start_page > effective_end_page:
            raise ValueError(
                f"ช่วงหน้าที่ต้องการ ({start_page}-{effective_end_page}) ไม่ถูกต้อง"
            )

        page_numbers: List[int] = []
        page_images: List[bytes] = []

        start_idx = start_page - 1
        end_idx = effective_end_page - 1

        for i in range(start_idx, end_idx + 1):
            page = doc.load_page(i)
            pix = page.get_pixmap(dpi=dpi)
            img_bytes = pix.tobytes("png")
            page_numbers.append(i + 1)
            page_images.append(img_bytes)

        return {
            "total_pages": total_pages,
            "page_numbers": page_numbers,
            "page_images": page_images,
        }
    finally:
        doc.close()


async def _timed_ocr_page(img_bytes: bytes, page_no: int) -> Dict:
    """OCR หน้าหนึ่ง + จับเวลาต่อหน้า"""
    start_t = time.perf_counter()
    text = await ocr_image_bytes(img_bytes, suffix=".png")
    duration = time.perf_counter() - start_t
    return {
        "page": page_no,
        "ocr": text,
        "ocr_seconds": round(duration, 3),
    }


# ===== ENDPOINT: OCR PDF =====
@app.post("/ocr_pdf")
async def ocr_pdf(
    file: UploadFile = File(...),
    start_page: int = Query(
        1,
        ge=1,
        description="เริ่มจากหน้าที่เท่าไหร่ (เริ่มที่ 1)",
    ),
    end_page: Optional[int] = Query(
        None,
        description="สิ้นสุดที่หน้าที่เท่าไหร่ (ไม่ระบุ = ถึงหน้าสุดท้าย)",
    ),
    max_pages: int = Query(
        20,
        ge=1,
        le=MAX_PAGES_HARD_LIMIT,
        description="จำนวนหน้าสูงสุดที่จะ OCR (กัน PDF ยาวเกินไป)",
    ),
    dpi: int = Query(
        200,
        ge=72,
        le=600,
        description="DPI ตอนแปลงหน้า PDF เป็นรูป (ยิ่งมากยิ่งคม แต่ช้าขึ้น/RAM เพิ่ม)",
    ),
):
    """
    OCR PDF หลายหน้า:
    - ใช้ PyMuPDF แปลงแต่ละหน้า → PNG ในหน่วยความจำ (รันใน thread แยก)
    - ส่ง PNG แต่ละหน้าเข้า typhoon_ocr.ocr_document แบบ parallel (จำกัด OCR_MAX_PARALLEL)
    - เก็บเวลารวมทั้งไฟล์ + เวลา OCR ต่อหน้า
    """
    start_time_total = time.perf_counter()

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="ไฟล์ว่างเปล่า")

    _validate_upload_size(pdf_bytes, file.filename or "unknown")

    # basic signature check เพื่อกันไฟล์แฝงที่ไม่ใช่ PDF
    if not pdf_bytes.lstrip().startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="ไฟล์ที่ส่งมาไม่ใช่ PDF ที่ถูกต้อง")

    # คำนวณช่วงหน้าเบื้องต้น
    if end_page is not None and end_page < start_page:
        raise HTTPException(
            status_code=400,
            detail=f"end_page ({end_page}) ต้องไม่ต่ำกว่า start_page ({start_page})",
        )

    # ตัดด้วย max_pages ก่อน (เพราะไม่อยาก OCR เกิน limit)
    max_end_by_limit = start_page + max_pages - 1
    if end_page is None:
        effective_end_page = max_end_by_limit
    else:
        effective_end_page = min(end_page, max_end_by_limit)

    # render PDF → images ใน thread เพื่อไม่ block event loop
    try:
        pdf_render_result = await asyncio.to_thread(
            _pdf_to_images,
            pdf_bytes,
            start_page,
            effective_end_page,
            dpi,
        )
    except ValueError as e:
        # error จาก validation ข้างใน _pdf_to_images
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        # ไม่โชว์รายละเอียด exception จริง เพื่อความปลอดภัย
        raise HTTPException(status_code=400, detail="ไม่สามารถเปิดหรืออ่านไฟล์ PDF ได้")

    total_pages = pdf_render_result["total_pages"]
    page_numbers: List[int] = pdf_render_result["page_numbers"]
    page_images: List[bytes] = pdf_render_result["page_images"]

    # ถ้า effective_end_page เกินจริง (เช่น PDF หน้าน้อยกว่าที่คิด) ให้ปรับให้ตรง
    if page_numbers:
        effective_end_page_real = page_numbers[-1]
    else:
        raise HTTPException(status_code=400, detail="ไม่พบหน้าที่ต้องใช้ OCR")

    # OCR parallel + เก็บเวลาต่อหน้า
    ocr_start = time.perf_counter()
    tasks = [
        _timed_ocr_page(img_bytes, page_no)
        for img_bytes, page_no in zip(page_images, page_numbers)
    ]
    pages_output: List[Dict] = await asyncio.gather(*tasks)
    ocr_wall_seconds = time.perf_counter() - ocr_start

    # สร้าง full_text จาก OCR ทุกหน้า
    full_text = "\n\n==== PAGE BREAK ====\n\n".join(
        p["ocr"] for p in pages_output
    )

    total_duration = time.perf_counter() - start_time_total
    ocr_seconds_sum = sum(p["ocr_seconds"] for p in pages_output)
    avg_ocr_per_page = ocr_seconds_sum / len(pages_output) if pages_output else 0.0

    return {
        "status": "ok",
        "filename": file.filename,
        "total_pages_in_pdf": total_pages,
        "start_page": start_page,
        "end_page": effective_end_page_real,
        "processed_pages": len(pages_output),
        "dpi": dpi,
        "pages": pages_output,
        "full_text": full_text,
        # metrics ด้านเวลา
        "metrics": {
            # เวลารวมทั้ง endpoint (อ่านไฟล์ + render + OCR)
            "processing_seconds_total": round(total_duration, 3),
            # เวลาตั้งแต่เริ่ม OCR จริง ๆ (เฉพาะส่วน OCR, รวม effect จาก concurrency)
            "ocr_wall_seconds": round(ocr_wall_seconds, 3),
            # ผลรวมเวลาต่อหน้า (ไม่มีหัก concurrency) เอาไว้ดู load ต่อหน้า
            "ocr_seconds_sum": round(ocr_seconds_sum, 3),
            # เวลาเฉลี่ยต่อหน้า
            "ocr_seconds_avg_per_page": round(avg_ocr_per_page, 3),
        },
    }