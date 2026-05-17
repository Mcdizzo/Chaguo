#!/usr/bin/env python3
"""
Fetch the latest TCU undergraduate admission guidebook for holders of secondary
school qualifications, download it under data/guidebooks/, and optionally run
extract_requirements.py when a new file is saved.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UNDERGRAD_GUIDEBOOKS_URL = (
    "https://tcu.go.tz/services/admissions-coordination-and-database-management/"
    "admission-guidebooks/undergraduate"
)

# Repository root = parent of the tz_admissions package (contains data/, .env).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
GUIDEBOOKS_DIR = PROJECT_ROOT / "data" / "guidebooks"
MANIFEST_PATH = GUIDEBOOKS_DIR / "last_secondary_school_guidebook.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
log = logging.getLogger("update_guidebook")

USER_AGENT = "tz-admissions-guidebook-updater/1.0"


def is_secondary_school_pathway(link_text: str) -> bool:
    """True for F6 / secondary-school pathway; excludes diploma-equivalent track."""
    t = link_text.lower()
    if "diploma" in t and "equivalent" in t:
        return False
    if "ordinary diploma" in t:
        return False
    return (
        "holders of secondary school qualifications" in t
        or "form six applicants" in t
        or ("form six" in t and "guidebook" in t)
    )


def parse_academic_year(text: str) -> Optional[Tuple[int, int]]:
    """Return (start_year, end_year) e.g. (2025, 2026) from anchor text."""
    m = re.search(r"(\d{4})\s*/\s*(\d{4})", text)
    if not m:
        return None
    y1, y2 = int(m.group(1)), int(m.group(2))
    return (y1, y2)


def year_sort_key(years: Tuple[int, int]) -> Tuple[int, int]:
    return years


def find_latest_secondary_pdf(
    soup: BeautifulSoup, base_url: str
) -> Tuple[str, Tuple[int, int]]:
    """Pick the most recent PDF link for secondary-school qualifications."""
    candidates: list[Tuple[str, Tuple[int, int], str]] = []

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        if not href.lower().endswith(".pdf"):
            continue
        text = anchor.get_text(" ", strip=True)
        if not text or not is_secondary_school_pathway(text):
            continue
        years = parse_academic_year(text)
        if years is None:
            continue
        full_url = urljoin(base_url, href)
        candidates.append((full_url, years, text))

    if not candidates:
        raise RuntimeError(
            "No PDF link found for holders of secondary school qualifications "
            "(or Form Six) on the undergraduate guidebooks page."
        )

    candidates.sort(key=lambda c: year_sort_key(c[1]), reverse=True)
    best_url, best_years, _ = candidates[0]
    return best_url, best_years


def load_manifest() -> Optional[dict[str, Any]]:
    if not MANIFEST_PATH.is_file():
        return None
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Could not read manifest (%s); will treat as no prior download.", e)
        return None


def save_manifest(url: str, local_relpath: str, academic_year: str) -> None:
    payload = {
        "pdf_url": url,
        "local_file": local_relpath,
        "academic_year": academic_year,
    }
    MANIFEST_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log.info("Wrote manifest: %s", MANIFEST_PATH)


def remote_pdf_content_length(session: requests.Session, url: str) -> int | None:
    """Return Content-Length from a HEAD request, if the server sends it."""
    try:
        h = session.head(url, allow_redirects=True, timeout=60)
        h.raise_for_status()
        cl = h.headers.get("Content-Length")
        if cl is not None and str(cl).isdigit():
            return int(cl)
    except requests.RequestException as e:
        log.warning("HEAD request failed (%s); cannot verify PDF size remotely.", e)
    return None


def should_skip_download(
    session: requests.Session,
    latest_url: str,
    dest_path: Path,
    *,
    force: bool,
) -> bool:
    """
    Skip re-download only if manifest URL matches, file exists, and size matches
    remote Content-Length (avoids treating truncated downloads as 'up to date').
    """
    if force:
        log.info("--force: re-downloading guidebook.")
        return False
    manifest = load_manifest()
    if manifest is None:
        return False
    if manifest.get("pdf_url") != latest_url:
        return False
    if not dest_path.is_file():
        return False

    expected = remote_pdf_content_length(session, latest_url)
    if expected is None:
        log.warning(
            "Could not verify remote file size; keeping existing file. "
            "Use --force if the PDF is corrupt."
        )
        return True

    actual = dest_path.stat().st_size
    if actual != expected:
        log.warning(
            "Local PDF is incomplete or wrong size (%s bytes); remote is %s bytes — "
            "will re-download.",
            actual,
            expected,
        )
        return False

    log.info(
        "Guidebook already up to date (file size matches remote: %s bytes).",
        actual,
    )
    return True


def download_pdf(session: requests.Session, url: str, dest: Path) -> None:
    """Stream download to disk and verify byte count against Content-Length."""
    log.info("Download started: %s", url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    # Long read timeout: large PDFs over slow links
    read_timeout = 600
    written = 0
    try:
        with session.get(
            url,
            stream=True,
            timeout=(30, read_timeout),
            headers={"Accept-Encoding": "identity"},
        ) as resp:
            resp.raise_for_status()
            expected: int | None = None
            cl = resp.headers.get("Content-Length")
            if cl is not None and str(cl).isdigit():
                expected = int(cl)
                log.info("Expecting %s bytes (Content-Length).", expected)

            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        written += len(chunk)

            if expected is not None and written != expected:
                raise OSError(
                    f"Incomplete download: wrote {written} bytes, expected {expected} "
                    f"(connection may have dropped early — try again or use --force)."
                )

        tmp.replace(dest)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise
    else:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    log.info("Download complete: %s (%s bytes)", dest, dest.stat().st_size)


def trigger_extraction(pdf_path: Path) -> None:
    extractor = PROJECT_ROOT / "tz_admissions" / "pipeline" / "extract_requirements.py"
    if not extractor.is_file():
        log.error(
            "extract_requirements.py not found at %s — skipping extraction trigger.",
            extractor,
        )
        return
    log.info("Extraction triggered: %s %s", sys.executable, extractor)
    try:
        subprocess.run(
            [sys.executable, str(extractor), str(pdf_path)],
            cwd=str(PROJECT_ROOT),
            check=True,
        )
        log.info("extract_requirements.py finished successfully.")
    except subprocess.CalledProcessError as e:
        log.error("extract_requirements.py exited with code %s", e.returncode)
        raise
    except OSError as e:
        log.error("Failed to run extract_requirements.py: %s", e)
        raise


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Download the latest TCU secondary-school undergraduate guidebook PDF."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if the manifest matches (fixes truncated/corrupt PDFs).",
    )
    parser.add_argument(
        "--no-extract",
        action="store_true",
        help="Download only; do not run extract_requirements.py.",
    )
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    try:
        log.info("Fetching guidebook index: %s", UNDERGRAD_GUIDEBOOKS_URL)
        r = session.get(UNDERGRAD_GUIDEBOOKS_URL, timeout=60)
        r.raise_for_status()
    except requests.RequestException as e:
        log.error("Failed to fetch undergraduate guidebooks page: %s", e)
        return 1

    soup = BeautifulSoup(r.text, "html.parser")
    base = r.url

    try:
        latest_url, (y1, y2) = find_latest_secondary_pdf(soup, base)
    except RuntimeError as e:
        log.error("%s", e)
        return 1

    academic_year_label = f"{y1}/{y2}"
    filename = f"undergraduate_secondary_school_{y1}_{y2}.pdf"
    dest = GUIDEBOOKS_DIR / filename

    if should_skip_download(session, latest_url, dest, force=args.force):
        return 0

    log.info(
        "Latest secondary-school guidebook: %s (%s)",
        academic_year_label,
        latest_url,
    )

    try:
        download_pdf(session, latest_url, dest)
    except requests.RequestException as e:
        log.error("Download failed: %s", e)
        return 1
    except OSError as e:
        log.error("Failed to save PDF: %s", e)
        return 1

    save_manifest(
        latest_url,
        str(dest.relative_to(PROJECT_ROOT)),
        academic_year_label,
    )

    if not args.no_extract:
        try:
            trigger_extraction(dest)
        except (subprocess.CalledProcessError, OSError):
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
