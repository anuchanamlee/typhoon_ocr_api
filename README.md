# Typhoon OCR API

[![CI](https://github.com/anuchanamlee/typhoon_ocr_api/actions/workflows/ci.yml/badge.svg)](https://github.com/anuchanamlee/typhoon_ocr_api/actions/workflows/ci.yml)

A REST API for Thai-language OCR on images and multi-page PDFs, running on a
self-hosted model ([Typhoon OCR 1.5](https://ollama.com/scb10x/typhoon-ocr1.5-3b)
served by Ollama). No document leaves your own machine.

[ภาษาไทย](README.th.md)

## How it works

```
client ──multipart──▶ FastAPI ──PyMuPDF──▶ PNG per page
                         │
                         └─▶ typhoon_ocr.ocr_document ──▶ Ollama (/v1/chat/completions)
                               (max OCR_MAX_PARALLEL at once)
```

- PDF pages are rendered in a worker thread (`asyncio.to_thread`) so the event loop stays free.
- Pages are OCR'd concurrently, bounded by an `asyncio.Semaphore` so a long PDF cannot flood the model server.
- Every response reports timing: total, OCR wall-clock, sum and average per page — enough to size hardware.

## Guard rails

| Risk | Limit |
|---|---|
| Huge upload | `MAX_UPLOAD_SIZE_MB` (default 50) → HTTP 413 |
| Very long PDF | `max_pages` per request (default 20, hard cap `MAX_PAGES_HARD_LIMIT` = 100) |
| Non-PDF sent to `/ocr_pdf` | `%PDF` signature check → HTTP 400 |
| Non-image sent to `/ocr_image` | MIME check → HTTP 400 |
| Unreadable PDF | Generic HTTP 400; parser details are not echoed back |

## Run

1. Start Ollama and pull the model:

   ```bash
   docker run -d --name ollama -p 11434:11434 ollama/ollama
   docker exec ollama ollama pull scb10x/typhoon-ocr1.5-3b
   ```

2. Start the API:

   ```bash
   docker build -t typhoon-ocr-api .
   docker run -d -p 8000:8000 \
     -e TYPHOON_BASE_URL=http://host.docker.internal:11434/v1 \
     typhoon-ocr-api
   ```

Docs: http://localhost:8000/docs

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

The model is replaced by a fake, so tests run anywhere without Ollama. They cover
input validation (MIME, `%PDF` signature, empty and oversized uploads, page and DPI
bounds), page selection (`start_page`, `end_page`, `max_pages`, clamping to the real
page count), response order when pages finish out of order, temp-file cleanup, and
that no more than `OCR_MAX_PARALLEL` pages are sent to the model at once.
CI runs them on every push and pull request, then builds the Docker image.

## Configuration

| Variable | Default |
|---|---|
| `TYPHOON_BASE_URL` | `http://localhost:11434/v1` |
| `TYPHOON_API_KEY` | `ollama` |
| `TY_OCR_MODEL` | `scb10x/typhoon-ocr1.5-3b` |
| `OCR_MAX_PARALLEL` | `2` |
| `MAX_PAGES_HARD_LIMIT` | `100` |
| `MAX_UPLOAD_SIZE_MB` | `50` |

## API

**`POST /ocr_image`** — one image (`file`). Returns `ocr` text and `processing_seconds`.

**`POST /ocr_pdf`** — one PDF (`file`). Query: `start_page`, `end_page`, `max_pages`, `dpi` (72–600, default 200).

```bash
curl -X POST "http://localhost:8000/ocr_pdf?start_page=1&max_pages=5" -F "file=@invoice.pdf"
```

Response (shape):

```json
{
  "status": "ok",
  "total_pages_in_pdf": 4,
  "processed_pages": 4,
  "pages": [{ "page": 1, "ocr": "...", "ocr_seconds": 0.0 }],
  "full_text": "...",
  "metrics": {
    "processing_seconds_total": 0.0,
    "ocr_wall_seconds": 0.0,
    "ocr_seconds_sum": 0.0,
    "ocr_seconds_avg_per_page": 0.0
  }
}
```

## Stack

Python · FastAPI · PyMuPDF · Ollama · Typhoon OCR · Docker

## License

MIT
