"""
app/admin/sheet_scraper.py
--------------------------
Scrapes a Codolio sheet page using Playwright (headless Chromium).

Strategy: Intercept XHR/fetch responses made by the Next.js app.
Codolio fetches question data from their internal API on page load.
We capture that API response directly — much faster and more reliable
than DOM scraping.

Fallback: If no API response is captured, parse the rendered HTML.

Install once:  pip install playwright && playwright install chromium

STATS POLICY
------------
Stats (totalAccepted, totalSubmissions, acceptanceRate, likes, dislikes)
are NEVER imported from any external source.  They always start at zero
and are updated exclusively through this application's own submission /
like / dislike interactions.  This is enforced by:
  1. _normalise_question()  — whitelist-only field extraction (no stats keys)
  2. ZERO_STATS constant    — used by the save route for every question
"""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# STATS POLICY — always start at zero, grow from app interactions only
# ---------------------------------------------------------------------------
# This constant is the single source of truth for initial question stats.
# It is used by the admin save route (_save_imported_sheet) and must NEVER
# be populated from an external scrape result.
ZERO_STATS: dict = {
    "totalAccepted":   0,
    "totalSubmissions": 0,
    "acceptanceRate":  0.0,
    "likes":           0,
    "dislikes":        0,
}

# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------
CODOLIO_SHEET_RE = re.compile(
    r"^https?://(?:www\.)?codolio\.com/question-tracker/sheet/([a-zA-Z0-9_-]+)$"
)


def validate_codolio_url(url: str) -> tuple[bool, str]:
    """Return (ok, error_message). ok=True means URL is valid."""
    url = (url or "").strip()
    if not url:
        return False, "URL is required."
    if not CODOLIO_SHEET_RE.match(url):
        return False, (
            "URL must be a Codolio sheet URL like: "
            "https://codolio.com/question-tracker/sheet/love-babbar-sheet"
        )
    return True, ""


def _sheet_slug_from_url(url: str) -> str:
    m = CODOLIO_SHEET_RE.match(url.strip())
    return m.group(1) if m else urlparse(url).path.rstrip("/").split("/")[-1]


# ---------------------------------------------------------------------------
# Scrape with Playwright (primary method)
# ---------------------------------------------------------------------------
def _scrape_with_playwright(url: str, timeout_ms: int = 30_000) -> dict[str, Any]:
    """
    Open the Codolio sheet page in headless Chromium, intercept XHR responses,
    and return structured question data.

    Returns a dict:
    {
        "sheet_name": str,
        "sheet_slug": str,
        "description": str,
        "questions": [
            {
                "title": str,
                "difficulty": str,         # "Easy" | "Medium" | "Hard"
                "topics": list[str],
                "companies": list[str],
                "url": str,                # primary problem URL
                "url2": str,               # secondary URL (optional)
                "lc_id": int | None,
                "lc_slug": str,
            },
            ...
        ],
        "total": int,
        "source": "playwright_api" | "playwright_html",
        "error": str | None,
    }
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

    captured_questions: list[dict] = []
    sheet_meta: dict = {}
    api_captured = False

    def _handle_response(response):
        nonlocal api_captured
        if api_captured:
            return
        try:
            url_resp = response.url.lower()
            # Codolio fetches questions from endpoints like /api/... or graphql or /_next/...
            if response.status != 200:
                return
            ct = response.headers.get("content-type", "")
            if "json" not in ct:
                return
            # Only intercept calls that look like question-data endpoints
            keywords = ["sheet", "question", "tracker", "problem"]
            if not any(k in url_resp for k in keywords):
                return
            body = response.json()
            qs = _extract_questions_from_json(body)
            if qs:
                captured_questions.extend(qs)
                meta = _extract_meta_from_json(body)
                sheet_meta.update(meta)
                api_captured = True
        except Exception:
            pass

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()
        page.on("response", _handle_response)

        try:
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        except PWTimeoutError:
            pass  # page may still have loaded enough data

        # Give extra time for lazy-loaded API calls
        try:
            page.wait_for_timeout(3000)
            # Scroll down to trigger any virtual scroll / pagination
            for _ in range(5):
                page.keyboard.press("End")
                page.wait_for_timeout(800)
        except Exception:
            pass

        source = "playwright_api"
        if not captured_questions:
            # Fallback: parse HTML
            source = "playwright_html"
            html = page.content()
            captured_questions = _parse_html_questions(html)
            sheet_meta = _parse_html_meta(html)

        # Also try reading sheet title from page title / h1
        if not sheet_meta.get("sheet_name"):
            try:
                h1 = page.locator("h1").first.text_content(timeout=2000)
                if h1:
                    sheet_meta["sheet_name"] = h1.strip()
            except Exception:
                pass

        context.close()
        browser.close()

    slug = _sheet_slug_from_url(url)
    name = sheet_meta.get("sheet_name") or _humanize_slug(slug)
    description = sheet_meta.get("description") or f"Imported from Codolio: {name}"

    return {
        "sheet_name": name,
        "sheet_slug": slug,
        "description": description,
        "questions": _dedupe_questions(captured_questions),
        "total": len(captured_questions),
        "source": source,
        "error": None,
    }


# ---------------------------------------------------------------------------
# JSON response parsers
# ---------------------------------------------------------------------------
def _extract_questions_from_json(body: Any) -> list[dict]:
    """Try to find a list of question objects anywhere in an arbitrary JSON blob."""
    candidates: list[dict] = []

    def _walk(node):
        if isinstance(node, list):
            for item in node:
                _walk(item)
        elif isinstance(node, dict):
            # Heuristic: a question object typically has 'title' or 'name' + some URL field
            if _looks_like_question(node):
                q = _normalise_question(node)
                if q:
                    candidates.append(q)
            else:
                for v in node.values():
                    _walk(v)

    _walk(body)
    return candidates


def _looks_like_question(node: dict) -> bool:
    has_title = any(k in node for k in ("title", "name", "questionTitle", "problemTitle", "problem"))
    has_link = any(
        k in node
        for k in ("problemUrl", "url", "link", "href", "leetcodeUrl", "gfgUrl", "lcUrl")
    )
    has_diff = any(k in node for k in ("difficulty", "level"))
    return has_title and (has_link or has_diff)


def _normalise_question(node: dict) -> dict | None:
    title = (
        node.get("title")
        or node.get("name")
        or node.get("questionTitle")
        or node.get("problemTitle")
        or node.get("problem")
        or ""
    ).strip()
    if not title:
        return None

    difficulty = (
        node.get("difficulty")
        or node.get("level")
        or "Medium"
    )
    difficulty = _normalise_difficulty(difficulty)

    topics = _list_field(node, ("topics", "tags", "categories", "topic"))
    companies = _list_field(node, ("companyTags", "companies", "company", "askedBy"))

    url = (
        node.get("problemUrl")
        or node.get("url")
        or node.get("link")
        or node.get("href")
        or node.get("leetcodeUrl")
        or node.get("lcUrl")
        or node.get("gfgUrl")
        or ""
    ).strip()
    url2 = (
        node.get("url2")
        or node.get("secondaryUrl")
        or node.get("gfgUrl")
        or node.get("cnUrl")
        or ""
    ).strip()
    if url == url2:
        url2 = ""

    lc_id = (
        node.get("lcId")
        or node.get("leetcodeId")
        or node.get("questionId")
        or node.get("id")
        or None
    )
    lc_slug = (
        node.get("lcSlug")
        or node.get("titleSlug")
        or node.get("lcTitleSlug")
        or node.get("slug")
        or ""
    ).strip()

    return {
        "title": title,
        "difficulty": difficulty,
        "topics": topics,
        "companies": companies,
        "url": url,
        "url2": url2,
        "lc_id": _safe_int(lc_id),
        "lc_slug": lc_slug,
    }


def _extract_meta_from_json(body: Any) -> dict:
    meta: dict = {}
    if isinstance(body, dict):
        meta["sheet_name"] = (
            body.get("sheetName")
            or body.get("name")
            or body.get("title")
            or ""
        )
        meta["description"] = body.get("description") or ""
    return meta


# ---------------------------------------------------------------------------
# HTML fallback parsers
# ---------------------------------------------------------------------------
def _parse_html_questions(html: str) -> list[dict]:
    """Last-resort: extract visible text rows from rendered HTML."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    questions = []

    # Find all anchor tags pointing to known OJs
    KNOWN_OJS = ("leetcode.com", "geeksforgeeks.org", "naukri.com/code360", "codingninjas.com", "hackerrank.com", "interviewbit.com")

    seen_titles: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not any(oj in href for oj in KNOWN_OJS):
            continue
        title = a.get_text(strip=True)
        if not title or len(title) < 3:
            # Try parent row
            parent = a.find_parent(["li", "tr", "div"])
            if parent:
                title = parent.get_text(separator=" ", strip=True)[:120]
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        # Guess difficulty from surrounding text
        row_text = ""
        parent = a.find_parent(["li", "tr", "div"])
        if parent:
            row_text = parent.get_text().lower()
        difficulty = "Medium"
        if "easy" in row_text:
            difficulty = "Easy"
        elif "hard" in row_text:
            difficulty = "Hard"

        questions.append({
            "title": title,
            "difficulty": difficulty,
            "topics": [],
            "companies": [],
            "url": href,
            "url2": "",
            "lc_id": None,
            "lc_slug": "",
        })

    return questions


def _parse_html_meta(html: str) -> dict:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    name = h1.get_text(strip=True) if h1 else ""
    desc_tag = soup.find("meta", {"name": "description"})
    desc = desc_tag["content"] if desc_tag else ""
    return {"sheet_name": name, "description": desc}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _normalise_difficulty(raw: Any) -> str:
    raw = str(raw).strip().lower()
    if raw in ("easy", "0", "beginner"):
        return "Easy"
    if raw in ("hard", "2", "advanced"):
        return "Hard"
    return "Medium"


def _list_field(node: dict, keys: tuple) -> list[str]:
    for k in keys:
        val = node.get(k)
        if isinstance(val, list):
            return [str(v).strip() for v in val if v]
        if isinstance(val, str) and val:
            return [val.strip()]
    return []


def _safe_int(val: Any) -> int | None:
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _humanize_slug(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title()


def _dedupe_questions(questions: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for q in questions:
        key = q["title"].lower().strip()
        if key not in seen:
            seen.add(key)
            out.append(q)
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def scrape_codolio_sheet(url: str) -> dict[str, Any]:
    """
    Scrape a Codolio sheet URL.  Returns a result dict (never raises).

    Result keys:
        sheet_name, sheet_slug, description,
        questions (list), total (int),
        source (str), error (str|None)
    """
    ok, err = validate_codolio_url(url)
    if not ok:
        return {"error": err, "questions": [], "total": 0,
                "sheet_name": "", "sheet_slug": "", "description": "", "source": "none"}

    try:
        return _scrape_with_playwright(url)
    except ImportError:
        return {
            "error": (
                "Playwright is not installed. "
                "Run: pip install playwright && playwright install chromium"
            ),
            "questions": [],
            "total": 0,
            "sheet_name": "",
            "sheet_slug": _sheet_slug_from_url(url),
            "description": "",
            "source": "none",
        }
    except Exception as exc:
        return {
            "error": f"Scraping failed: {exc}",
            "questions": [],
            "total": 0,
            "sheet_name": "",
            "sheet_slug": _sheet_slug_from_url(url),
            "description": "",
            "source": "none",
        }
