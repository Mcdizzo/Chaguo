#!/usr/bin/env python3
"""
Extract undergraduate program requirements from TCU guidebook PDFs using PyMuPDF
and the Groq API, then load rows into SQLite (tz_admissions database).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

# Repository root = parent of the tz_admissions package (contains data/, .env).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tz_admissions"))

from dotenv import load_dotenv

from database.db import (
    count_extracted_programs,
    delete_programs_for_university,
    find_uni_id_by_name,
    get_connection,
    init_db,
    insert_guidebook_programs,
    insert_university_if_missing,
)

load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
log = logging.getLogger("extract_requirements")

INTRO_PAGES_SKIP = 24

UNIVERSITY_HEADER_RE = re.compile(
    r"^\s*(.+?)\s+\(([^)]+)\)\s*,\s*(.+?)\s*$"
)

PROGRAM_CODE_SPLIT_RE = re.compile(r"(?=\n\s*\d+\.\s+\w)", re.MULTILINE)

EXTRACTION_PROMPT = (
    "Extract all university programs from this text and return ONLY a JSON array "
    "with no markdown or extra text. Each object should have: university_name, "
    "program_code, program_name, duration_years, minimum_points, admission_capacity, "
    "admission_requirements_raw (the full requirements paragraph as a string)"
)

GROQ_MODEL = "llama-3.3-70b-versatile"


def find_latest_guidebook_pdf(guide_dir: Path) -> Path:
    """Return the most recently modified PDF under data/guidebooks/."""
    if not guide_dir.is_dir():
        raise FileNotFoundError(f"Guidebook directory not found: {guide_dir}")
    pdfs = sorted(
        guide_dir.glob("*.pdf"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not pdfs:
        raise FileNotFoundError(f"No PDF files in {guide_dir}")
    return pdfs[0]


def extract_text_after_intro(pdf_path: Path) -> str:
    """Extract text using PyMuPDF (fitz), skip introductory pages."""
    try:
        import fitz
    except ImportError as e:
        raise RuntimeError(
            "PyMuPDF not found. Install it: pip install pymupdf"
        ) from e

    doc = fitz.open(str(pdf_path))
    total = len(doc)
    log.info(
        "PyMuPDF opened %s page(s); skipping first %s (intro).",
        total,
        INTRO_PAGES_SKIP,
    )

    parts: list[str] = []
    for i, page in enumerate(doc):
        if i < INTRO_PAGES_SKIP:
            continue
        t = page.get_text().strip()
        if t:
            parts.append(t)

    doc.close()
    return "\n\n".join(parts)


def looks_like_university_header_line(line: str) -> bool:
    """Reduce false positives: TOC lines etc."""
    s = line.strip()
    if len(s) < 10 or len(s) > 220:
        return False
    if UNIVERSITY_HEADER_RE.match(s) is None:
        return False
    lower = s.lower()
    if "diploma" in lower and "equivalent" in lower:
        return False
    return True


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).lower()


def split_chunks_by_university(full_text: str) -> list[tuple[str, str, str]]:
    """
    Split text into chunks by university section.
    Returns list of (header_line, university_name, chunk_body).
    """
    lines = full_text.splitlines()
    chunks: list[tuple[str, str, str]] = []
    preamble: list[str] = []
    current_header: str | None = None
    current_name: str | None = None
    current_body: list[str] = []

    def flush() -> None:
        nonlocal current_header, current_name, current_body
        if current_header and current_name is not None:
            body = "\n".join(current_body).strip()
            chunks.append((current_header, current_name, body))
        current_header = None
        current_name = None
        current_body = []

    for line in lines:
        stripped = line.strip()
        if looks_like_university_header_line(stripped):
            m = UNIVERSITY_HEADER_RE.match(stripped)
            if not m:
                if current_header:
                    current_body.append(line)
                else:
                    preamble.append(line)
                continue
            name_part = m.group(1).strip()
            if current_name and normalize_name(name_part) == normalize_name(current_name):
                # Same university continuing on next page — keep appending
                current_body.append(line)
            else:
                if current_header:
                    flush()
                current_header = stripped
                current_name = name_part
                current_body = [line]
        elif current_header:
            current_body.append(line)
        else:
            preamble.append(line)

    flush()

    if preamble and chunks:
        pre = "\n".join(preamble).strip()
        if pre:
            h, n, b = chunks[0]
            chunks[0] = (h, n, pre + "\n\n" + b)
    elif preamble and not chunks:
        log.warning(
            "No university header lines matched; preamble length=%s chars. "
            "Check PDF text or header regex.",
            len(preamble),
        )

    return chunks


def strip_json_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


def parse_llm_json_array(text: str) -> list[dict[str, Any]]:
    raw = strip_json_fences(text)
    data = json.loads(raw)
    if isinstance(data, dict) and "programs" in data:
        data = data["programs"]
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array, got {type(data).__name__}")
    return [x for x in data if isinstance(x, dict)]


def coerce_program_row(obj: dict[str, Any]) -> dict[str, Any]:
    """Normalize types for SQLite insert."""
    raw_req = obj.get("admission_requirements_raw")
    if raw_req is None:
        raw_req = obj.get("admission_requirements")
    return {
        "program_name": (obj.get("program_name") or "").strip() or "Unknown program",
        "program_code": _str_or_none(obj.get("program_code")),
        "duration_years": _float_or_none(obj.get("duration_years")),
        "minimum_points": _float_or_none(obj.get("minimum_points")),
        "admission_capacity": _int_or_none(obj.get("admission_capacity")),
        "requirements_raw": _str_or_none(raw_req),
    }


def _str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _float_or_none(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    m = re.search(r"[-+]?\d*\.?\d+", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _int_or_none(v: Any) -> int | None:
    if v is None or v == "":
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    s = str(v).strip().replace(",", "")
    m = re.search(r"-?\d+", s)
    if not m:
        return None
    try:
        return int(m.group(0))
    except ValueError:
        return None


def call_groq_extract(chunk_text: str) -> list[dict[str, Any]]:
    """Send chunk to Groq and parse JSON array of programs."""
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set (add it to .env)")

    try:
        from groq import Groq
    except ImportError as e:
        raise RuntimeError("Install groq: pip install groq") from e

    client = Groq(api_key=api_key)
    full_prompt = f"{EXTRACTION_PROMPT}\n\n---\n\n{chunk_text}"

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": full_prompt}],
            temperature=0.1,
            max_tokens=8192,
        )
    except Exception as e:
        raise RuntimeError(f"Groq API request failed: {e}") from e

    text = response.choices[0].message.content or ""
    if not text.strip():
        raise RuntimeError("Empty response from Groq")

    return parse_llm_json_array(text)


def _extract_batch(batch_text: str) -> list[dict[str, Any]]:
    try:
        results = call_groq_extract(batch_text)
        log.info("Batch extracted %s programs.", len(results))
        return results
    except Exception as e:
        log.warning("Batch extraction failed: %s", e)
        return []


def extract_in_batches(chunk_text: str, batch_size: int = 15) -> list[dict[str, Any]]:
    """Split chunk into smaller batches by program code and extract each."""
    segments = PROGRAM_CODE_SPLIT_RE.split(chunk_text)
    all_results: list[dict[str, Any]] = []
    batch: list[str] = []

    for segment in segments:
        batch.append(segment)
        if len(batch) >= batch_size:
            all_results.extend(_extract_batch("\n".join(batch)))
            batch = []
            time.sleep(0.5)

    if batch:
        all_results.extend(_extract_batch("\n".join(batch)))

    return all_results


def resolve_uni_id(conn, uni_name: str, header: str) -> int | None:
    """Match existing university or insert from guidebook header."""
    uni_id = find_uni_id_by_name(conn, uni_name)
    if uni_id is None:
        alt = uni_name.replace("\xa0", " ").strip()
        uni_id = find_uni_id_by_name(conn, alt)
    if uni_id is not None:
        return uni_id

    log.warning(
        "No database match for %r — inserting from guidebook.",
        uni_name,
    )
    try:
        uni_id = insert_university_if_missing(conn, uni_name, header)
        log.info("Auto-inserted university with uni_id=%s", uni_id)
        return uni_id
    except Exception as e:
        log.error("Failed to auto-insert university %r: %s", uni_name, e)
        return None


def run(
    pdf_path: Path,
    *,
    dry_run: bool,
    max_universities: int | None,
) -> int:
    guide_dir = PROJECT_ROOT / "data" / "guidebooks"
    if not pdf_path.is_file():
        log.error("PDF not found: %s", pdf_path)
        return 1

    log.info("Using guidebook: %s", pdf_path)

    try:
        body = extract_text_after_intro(pdf_path)
    except Exception as e:
        log.error("%s", e)
        return 1

    if not body.strip():
        log.error("No text extracted after intro pages.")
        return 1

    chunks = split_chunks_by_university(body)
    log.info("Split into %s university section(s).", len(chunks))
    if len(chunks) <= 2 and body and len(body) > 50000:
        log.warning(
            "Very few university sections for a large guidebook — header lines may not "
            "match 'Name (ACRONYM), Location'. Consider tuning UNIVERSITY_HEADER_RE."
        )
    if not chunks:
        return 1

    if max_universities is not None:
        chunks = chunks[:max_universities]
        log.info("Limiting to first %s university section(s).", len(chunks))

    if dry_run:
        for i, (header, name, chunk) in enumerate(chunks, start=1):
            log.info(
                "[dry-run] %s | name=%s | chunk_chars=%s",
                i,
                name[:80] + ("…" if len(name) > 80 else ""),
                len(chunk),
            )
        log.info("Dry run complete — no API calls or database writes.")
        return 0

    conn = get_connection()
    init_db(conn)

    failed = 0
    for i, (header, uni_name, chunk) in enumerate(chunks, start=1):
        log.info(
            "Processing university %s/%s: %s",
            i,
            len(chunks),
            uni_name[:100] + ("…" if len(uni_name) > 100 else ""),
        )

        uni_id = resolve_uni_id(conn, uni_name, header)
        if uni_id is None:
            failed += 1
            continue

        existing = count_extracted_programs(conn, uni_id)
        if existing > 0:
            log.info(
                "Skipping %r — already has %s programs extracted.",
                uni_name,
                existing,
            )
            continue

        try:
            rows_raw = extract_in_batches(chunk)
        except Exception as e:
            log.error("Extraction failed for %r: %s", uni_name, e)
            failed += 1
            continue

        programs = [coerce_program_row(r) for r in rows_raw]
        if not programs:
            log.warning("No programs returned for %r — skipping DB write.", uni_name)
            failed += 1
            continue

        try:
            delete_programs_for_university(conn, uni_id)
            n = insert_guidebook_programs(conn, uni_id, programs)
            log.info("Inserted %s program(s) for uni_id=%s (%s).", n, uni_id, uni_name)
        except Exception as e:
            log.error("Database insert failed for %r: %s", uni_name, e)
            failed += 1
            continue

        time.sleep(0.4)

    conn.close()
    if failed:
        log.warning("Completed with %s failure(s).", failed)
        return 1 if failed == len(chunks) else 0
    log.info("All university sections processed successfully.")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Extract programs from TCU guidebook PDF into SQLite via Groq."
    )
    parser.add_argument(
        "pdf",
        nargs="?",
        default=None,
        help="Path to guidebook PDF (default: newest *.pdf under data/guidebooks/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Split PDF and log chunks only; no API or database writes.",
    )
    parser.add_argument(
        "--max-universities",
        type=int,
        default=None,
        help="Process only the first N university sections (useful for testing).",
    )
    args = parser.parse_args(argv[1:])

    guide_dir = PROJECT_ROOT / "data" / "guidebooks"
    try:
        pdf_path = Path(args.pdf).resolve() if args.pdf else find_latest_guidebook_pdf(guide_dir)
    except FileNotFoundError as e:
        log.error("%s", e)
        return 1

    return run(
        pdf_path,
        dry_run=args.dry_run,
        max_universities=args.max_universities,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
