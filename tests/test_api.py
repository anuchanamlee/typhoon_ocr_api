"""API tests with the OCR model replaced by a fake.

The real model runs in Ollama; these tests cover everything around it:
input validation, page selection, ordering, limits and concurrency.
"""

import threading
import time

import fitz  # PyMuPDF
import pytest
from fastapi.testclient import TestClient

import main


def make_pdf(pages: int) -> bytes:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"page {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


def make_png() -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)
    pix.clear_with(255)
    return pix.tobytes("png")


class FakeOcr:
    """Stands in for typhoon_ocr.ocr_document and records how it was called."""

    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.calls = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def __call__(self, pdf_or_image_path, base_url, api_key, model):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            n = len(self.calls) + 1
            self.calls.append(
                {"path": pdf_or_image_path, "base_url": base_url, "model": model}
            )
        try:
            # later calls finish first, so the response order must not follow completion order
            time.sleep(self.delay / n if self.delay else 0)
            with open(pdf_or_image_path, "rb") as f:
                size = len(f.read())
            return f"text#{n} ({size} bytes)"
        finally:
            with self._lock:
                self.active -= 1


@pytest.fixture
def fake_ocr(monkeypatch):
    fake = FakeOcr()
    monkeypatch.setattr(main, "ocr_document", fake)
    return fake


@pytest.fixture(scope="module")
def client():
    # One client for the whole module: inside `with`, every request runs on the
    # same event loop, like uvicorn does. The app's module-level asyncio.Semaphore
    # binds to the first loop that waits on it, so a loop per request would break it.
    with TestClient(main.app) as c:
        yield c


# ---------- /ocr_image ----------


def test_image_is_ocrd(client, fake_ocr):
    r = client.post("/ocr_image", files={"file": ("bill.png", make_png(), "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["filename"] == "bill.png"
    assert body["ocr"].startswith("text#1")
    assert len(fake_ocr.calls) == 1
    assert fake_ocr.calls[0]["path"].endswith(".png")
    assert fake_ocr.calls[0]["model"] == main.TYPHOON_MODEL


def test_image_temp_file_is_removed(client, fake_ocr):
    import os

    client.post("/ocr_image", files={"file": ("a.jpg", make_png(), "image/jpeg")})
    path = fake_ocr.calls[0]["path"]
    assert path.endswith(".jpg")
    assert not os.path.exists(path)


def test_image_rejects_non_image_mime(client, fake_ocr):
    r = client.post("/ocr_image", files={"file": ("a.pdf", make_pdf(1), "application/pdf")})
    assert r.status_code == 400
    assert fake_ocr.calls == []


def test_image_rejects_empty_file(client, fake_ocr):
    r = client.post("/ocr_image", files={"file": ("a.png", b"", "image/png")})
    assert r.status_code == 400
    assert fake_ocr.calls == []


def test_image_rejects_oversized_upload(client, fake_ocr, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_SIZE_MB", 0)
    r = client.post("/ocr_image", files={"file": ("a.png", make_png(), "image/png")})
    assert r.status_code == 413
    assert fake_ocr.calls == []


# ---------- /ocr_pdf ----------


def post_pdf(client, data: bytes, **params):
    return client.post(
        "/ocr_pdf",
        params=params,
        files={"file": ("doc.pdf", data, "application/pdf")},
    )


def test_pdf_all_pages_in_order(client, monkeypatch):
    fake = FakeOcr(delay=0.2)
    monkeypatch.setattr(main, "ocr_document", fake)

    r = post_pdf(client, make_pdf(3))
    assert r.status_code == 200
    body = r.json()
    assert body["total_pages_in_pdf"] == 3
    assert body["processed_pages"] == 3
    assert [p["page"] for p in body["pages"]] == [1, 2, 3]
    assert body["full_text"].count("==== PAGE BREAK ====") == 2
    for key in (
        "processing_seconds_total",
        "ocr_wall_seconds",
        "ocr_seconds_sum",
        "ocr_seconds_avg_per_page",
    ):
        assert body["metrics"][key] >= 0


def test_pdf_page_range(client, fake_ocr):
    r = post_pdf(client, make_pdf(5), start_page=2, end_page=4)
    assert r.status_code == 200
    body = r.json()
    assert [p["page"] for p in body["pages"]] == [2, 3, 4]
    assert body["start_page"] == 2 and body["end_page"] == 4


def test_pdf_max_pages_caps_the_range(client, fake_ocr):
    r = post_pdf(client, make_pdf(10), start_page=3, max_pages=2)
    assert r.status_code == 200
    assert [p["page"] for p in r.json()["pages"]] == [3, 4]
    assert len(fake_ocr.calls) == 2


def test_pdf_end_page_beyond_document_is_clamped(client, fake_ocr):
    r = post_pdf(client, make_pdf(2), end_page=9)
    assert r.status_code == 200
    body = r.json()
    assert body["end_page"] == 2
    assert body["processed_pages"] == 2


def test_pdf_start_page_beyond_document(client, fake_ocr):
    r = post_pdf(client, make_pdf(2), start_page=5)
    assert r.status_code == 400
    assert fake_ocr.calls == []


def test_pdf_end_before_start(client, fake_ocr):
    r = post_pdf(client, make_pdf(3), start_page=3, end_page=1)
    assert r.status_code == 400
    assert fake_ocr.calls == []


def test_pdf_max_pages_over_hard_limit_is_rejected(client, fake_ocr):
    r = post_pdf(client, make_pdf(1), max_pages=main.MAX_PAGES_HARD_LIMIT + 1)
    assert r.status_code == 422


@pytest.mark.parametrize("dpi", [71, 601])
def test_pdf_dpi_out_of_range(client, fake_ocr, dpi):
    r = post_pdf(client, make_pdf(1), dpi=dpi)
    assert r.status_code == 422


def test_pdf_rejects_non_pdf(client, fake_ocr):
    r = post_pdf(client, make_png())
    assert r.status_code == 400
    assert fake_ocr.calls == []


def test_pdf_corrupt_file_gets_generic_error(client, fake_ocr):
    r = post_pdf(client, b"%PDF-1.7\nthis is not really a pdf")
    assert r.status_code == 400
    detail = r.json()["detail"]
    # parser internals must not leak to the client
    assert "Traceback" not in detail and "fitz" not in detail.lower()
    assert fake_ocr.calls == []


def test_pdf_empty_file(client, fake_ocr):
    r = post_pdf(client, b"")
    assert r.status_code == 400


def test_pdf_oversized_upload(client, fake_ocr, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_SIZE_MB", 0)
    r = post_pdf(client, make_pdf(1))
    assert r.status_code == 413
    assert fake_ocr.calls == []


def test_pdf_ocr_concurrency_is_bounded(client, monkeypatch):
    fake = FakeOcr(delay=0.3)
    monkeypatch.setattr(main, "ocr_document", fake)

    r = post_pdf(client, make_pdf(6))
    assert r.status_code == 200
    assert len(fake.calls) == 6
    assert fake.max_active <= main.OCR_MAX_PARALLEL
    assert fake.max_active >= 2  # pages really do run in parallel
