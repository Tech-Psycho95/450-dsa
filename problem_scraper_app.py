"""Standalone GFG/LeetCode problem scraper with a small paste-a-URL web UI.

Run:
    python problem_scraper_app.py
Then open:
    http://127.0.0.1:5051

This application does not connect to MongoDB. Saved records go to
``scraped_problems.json`` beside this file.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template_string, request


OUTPUT_FILE = Path(__file__).with_name("scraped_problems.json")
SHEETS_FILE = Path(__file__).with_name("question_bank") / "sheets.json"
REQUEST_TIMEOUT = 25
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
)
STATS = {
    "totalAccepted": 0,
    "totalSubmissions": 0,
    "acceptanceRate": 0.0,
    "likes": 0,
    "dislikes": 0,
}

app = Flask(__name__)


class ScrapeError(ValueError):
    """A safe error that can be displayed in the UI."""


def detect_platform(url: str) -> str:
    """Return ``leetcode`` or ``gfg`` for a supported HTTPS URL."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if parsed.scheme not in {"http", "https"}:
        raise ScrapeError("Enter a complete http:// or https:// URL.")
    if host == "leetcode.com" or host.endswith(".leetcode.com"):
        return "leetcode"
    if host == "geeksforgeeks.org" or host.endswith(".geeksforgeeks.org"):
        return "gfg"
    raise ScrapeError("Only LeetCode and GeeksforGeeks URLs are supported.")


def clean_url(url: str) -> str:
    parsed = urlparse(url.strip())
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def slugify(value: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")


def text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def difficulty_marks(difficulty: str) -> int:
    return {"Basic": 2, "Easy": 3, "Medium": 4, "Hard": 8}.get(difficulty, 0)


def normalize_difficulty(value: Any) -> str:
    candidate = text(value).title()
    return candidate if candidate in {"Basic", "Easy", "Medium", "Hard"} else ""


def primary_topic(topics: list[str]) -> str:
    aliases = {
        "Arrays": "Array",
        "Strings": "String",
        "Linked List": "Linked List",
        "Tree": "Binary Tree",
        "Dynamic Programming": "Dynamic Programming",
    }
    return aliases.get(topics[0], topics[0]) if topics else ""


def blank_record(serial: int = 1) -> dict[str, Any]:
    timestamp = iso_now()
    return {
        "question_serial_number": serial,
        "questionId": serial,
        "titleSlug": "",
        "title": "",
        "content": "",
        "difficulty": "",
        "topics": [],
        "companies": [],
        "examples": [],
        "constraints": [],
        "similarQuestions": [],
        "starterCode": "",
        "stats": dict(STATS),
        "status": "published",
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "topic": "",
        "problem": "",
        "marks": 0,
        "expectedComplexity": {"time": "", "space": ""},
        "sheetName": "",
        "sheetNames": [],
        "sheetIds": [],
    }


def html_to_plain(value: str) -> str:
    soup = BeautifulSoup(value or "", "html.parser")
    for sup in soup.find_all("sup"):
        sup.replace_with("^" + sup.get_text("", strip=True))
    for br in soup.find_all("br"):
        br.replace_with("\n")
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True)).strip()


def problem_description(value: str) -> str:
    """Return only the statement before Example/Constraints sections."""
    plain = html_to_plain(value)
    return re.split(
        r"(?:^|\n)\s*(?:(?:Examples?|Constraints?)\s*\d*|Input)\s*:?\s*(?:\n|$)",
        plain,
        maxsplit=1,
        flags=re.I,
    )[0].strip()


def parse_examples_from_html(content: str) -> list[dict[str, str]]:
    plain = html_to_plain(content)
    pattern = re.compile(
        r"(?:Example\s*\d*\s*:?\s*)?Input\s*:\s*(.*?)\s*"
        r"Output\s*:\s*(.*?)(?=\s*(?:Explanation\s*:|Input\s*:|Example\s*\d*\s*:|Constraints\s*:|$))"
        r"(?:\s*Explanation\s*:\s*(.*?)(?=\s*(?:Input\s*:|Example\s*\d*\s*:|Constraints\s*:|"
        r"Try It Yourself|Table of Content|$)))?",
        re.I | re.S,
    )
    examples = []
    for match in pattern.finditer(plain):
        input_value, output_value, explanation = (text(v) for v in match.groups())
        if input_value and output_value:
            examples.append(
                {
                    "input": input_value,
                    "output": output_value,
                    "explanation": explanation,
                }
            )
    return examples[:4]


def parse_constraints(content: str) -> list[str]:
    soup = BeautifulSoup(content or "", "html.parser")
    for sup in soup.find_all("sup"):
        exponent = sup.get_text("", strip=True)
        separator = " ||| " if sup.find("br") else ""
        sup.replace_with((("^" + exponent) if exponent else "") + separator)
    for br in soup.find_all("br"):
        br.replace_with(" ||| ")
    heading = soup.find(
        lambda tag: tag.name in {"p", "strong", "h3", "h4"}
        and "constraint" in tag.get_text(" ", strip=True).lower()
    )
    if heading:
        container = heading.parent if heading.name == "strong" else heading
        container_text = container.get_text(" ", strip=True)
        if "constraint" in container_text.lower():
            tail = re.split(r"constraints?\s*:?", container_text, maxsplit=1, flags=re.I)[-1]
            values = []
            for line in tail.split("|||"):
                value = text(line).replace("\u2264", "<=").replace("\u2265", ">=")
                value = re.sub(r"\s+\^", "^", value)
                value = re.sub(r"(?<!\w)-\s+(?=\d)", "-", value)
                value = value.rstrip("^").strip()
                if not value:
                    continue
                if value.startswith("^") and values:
                    values[-1] += value
                else:
                    values.append(value)
            if values:
                return values[:6]
        sibling = container.find_next_sibling()
        if sibling:
            values = [text(x.get_text(" ", strip=True)) for x in sibling.find_all("li")]
            if values:
                return [x for x in values if x]
            lines = [text(x) for x in sibling.get_text("\n", strip=True).splitlines()]
            return [x for x in lines if x][:6]
    return []


def leetcode_slug(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if "problems" not in parts:
        raise ScrapeError("This does not look like a LeetCode problem URL.")
    index = parts.index("problems")
    if len(parts) <= index + 1:
        raise ScrapeError("The LeetCode problem slug is missing.")
    return parts[index + 1]


def scrape_leetcode(url: str, serial: int = 1) -> dict[str, Any]:
    slug = leetcode_slug(url)
    query = """
    query questionData($titleSlug: String!) {
      question(titleSlug: $titleSlug) {
        title titleSlug content difficulty exampleTestcases
        topicTags { name }
        codeSnippets { lang langSlug code }
        similarQuestions stats likes dislikes
      }
    }
    """
    response = requests.post(
        "https://leetcode.com/graphql",
        json={"query": query, "variables": {"titleSlug": slug}},
        headers={
            "User-Agent": USER_AGENT,
            "Referer": clean_url(url),
            "Content-Type": "application/json",
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    question = (response.json().get("data") or {}).get("question")
    if not question:
        raise ScrapeError("LeetCode did not return this problem. Check the URL or access level.")

    record = blank_record(serial)
    title = text(question.get("title"))
    topics = [text(item.get("name")) for item in question.get("topicTags") or [] if item.get("name")]
    snippets = question.get("codeSnippets") or []
    python_snippet = next(
        (item.get("code", "") for item in snippets if item.get("langSlug") in {"python3", "python"}),
        "",
    )
    similar = []
    try:
        similar_raw = json.loads(question.get("similarQuestions") or "[]")
        for item in similar_raw[:2]:
            similar.append(
                {
                    "title": text(item.get("title")),
                    "difficulty": normalize_difficulty(item.get("difficulty")),
                    "titleSlug": text(item.get("titleSlug")),
                }
            )
    except (TypeError, json.JSONDecodeError):
        pass

    stats = dict(STATS)
    try:
        source_stats = json.loads(question.get("stats") or "{}")
        stats["totalAccepted"] = source_stats.get("totalAcceptedRaw", 0) or 0
        stats["totalSubmissions"] = source_stats.get("totalSubmissionRaw", 0) or 0
        stats["acceptanceRate"] = float(str(source_stats.get("acRate", "0")).rstrip("%") or 0)
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    stats["likes"] = question.get("likes") or 0
    stats["dislikes"] = question.get("dislikes") or 0
    difficulty = normalize_difficulty(question.get("difficulty"))

    record.update(
        {
            "titleSlug": text(question.get("titleSlug")) or slugify(title),
            "title": title,
            "content": problem_description(question.get("content") or ""),
            "difficulty": difficulty,
            "topics": topics,
            "examples": parse_examples_from_html(question.get("content") or ""),
            "constraints": parse_constraints(question.get("content") or ""),
            "similarQuestions": similar,
            "starterCode": python_snippet,
            "stats": stats,
            "topic": primary_topic(topics),
            "problem": title,
            "marks": difficulty_marks(difficulty),
        }
    )
    return record


def extract_json_ld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    values = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            parsed = json.loads(script.string or script.get_text())
            if isinstance(parsed, list):
                values.extend(x for x in parsed if isinstance(x, dict))
            elif isinstance(parsed, dict):
                values.append(parsed)
        except (TypeError, json.JSONDecodeError):
            continue
    return values


def find_gfg_problem_data(value: Any) -> dict[str, Any] | None:
    """Find GFG's problem record inside its embedded Next.js state."""
    if isinstance(value, dict):
        if value.get("problem_name") and value.get("problem_question"):
            return value
        for child in value.values():
            found = find_gfg_problem_data(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_gfg_problem_data(child)
            if found:
                return found
    return None


def gfg_practice_data(soup: BeautifulSoup) -> dict[str, Any] | None:
    script = soup.select_one("script#__NEXT_DATA__")
    if not script:
        return None
    try:
        return find_gfg_problem_data(json.loads(script.string or script.get_text()))
    except (TypeError, json.JSONDecodeError):
        return None


def gfg_meta(slug: str) -> dict[str, Any]:
    """Fetch public metadata omitted from the initial GFG page state."""
    try:
        response = requests.get(
            f"https://practiceapi.geeksforgeeks.org/api/vr/problems/{slug}/metainfo/",
            headers={"User-Agent": USER_AGENT, "Referer": "https://www.geeksforgeeks.org/"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        value = response.json().get("results")
        return value if isinstance(value, dict) else {}
    except (requests.RequestException, ValueError, AttributeError):
        return {}


def gfg_problem_api(slug: str) -> dict[str, Any] | None:
    """Fetch a public GFG practice problem without relying on page hydration."""
    try:
        response = requests.get(
            f"https://practiceapi.geeksforgeeks.org/api/vr/problems/{slug}/",
            headers={"User-Agent": USER_AGENT, "Referer": "https://www.geeksforgeeks.org/"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        value = response.json().get("results")
        if isinstance(value, dict) and value.get("problem_name"):
            return value
    except (requests.RequestException, ValueError, AttributeError):
        pass
    return None


def gfg_problem_slug(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if "problems" in parts:
        index = parts.index("problems")
        if len(parts) > index + 1:
            return parts[index + 1]
    return ""


def scrape_gfg_practice(data: dict[str, Any], serial: int) -> dict[str, Any]:
    record = blank_record(serial)
    title = text(data.get("problem_name"))
    slug = text(data.get("slug")) or slugify(title)
    question_html = str(data.get("problem_question") or "")
    difficulty = normalize_difficulty(data.get("difficulty") or data.get("problem_level_text"))
    tags = data.get("tags") if isinstance(data.get("tags"), dict) else {}
    topics = [text(value) for value in tags.get("topic_tags") or [] if text(value)][:4]
    companies = [text(value) for value in tags.get("company_tags") or [] if text(value)][:3]
    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    functions = extra.get("initial_user_func") if isinstance(extra.get("initial_user_func"), dict) else {}
    python_data = functions.get("python3") or functions.get("python") or {}
    starter_code = text(python_data.get("user_code")) if isinstance(python_data, dict) else ""
    # Restore indentation/newlines removed by the generic text normalizer.
    if isinstance(python_data, dict) and python_data.get("user_code"):
        starter_code = str(python_data["user_code"]).strip()

    try:
        submissions = int(data.get("all_submissions") or 0)
    except (TypeError, ValueError):
        submissions = 0
    try:
        rate = float(str(data.get("accuracy") or "0").rstrip("%"))
    except ValueError:
        rate = 0.0
    stats = dict(STATS)
    stats.update(
        {
            "totalAccepted": round(submissions * rate / 100),
            "totalSubmissions": submissions,
            "acceptanceRate": rate,
        }
    )
    meta = gfg_meta(slug)
    record.update(
        {
            "titleSlug": slug,
            "title": title,
            "content": problem_description(question_html),
            "difficulty": difficulty,
            "topics": topics,
            "companies": companies,
            "examples": parse_examples_from_html(question_html),
            "constraints": parse_constraints(question_html),
            "starterCode": starter_code,
            "stats": stats,
            "topic": primary_topic(topics),
            "problem": title,
            "marks": int(data.get("marks") or difficulty_marks(difficulty)),
            "expectedComplexity": {
                "time": text(meta.get("expected_time_complexity")),
                "space": text(meta.get("expected_auxiliary_space")),
            },
        }
    )
    return record


def find_complexity(page_text: str) -> dict[str, str]:
    expected_heading = re.search(
        r"\[Expected Approach[^\]\n]*\][^\n]*?"
        r"(O\([^)]+\))\s*Time\s+and\s+(O\([^)]+\))\s*Space",
        page_text,
        re.I,
    )
    if expected_heading:
        return {"time": text(expected_heading.group(1)), "space": text(expected_heading.group(2))}
    time_match = re.search(r"(?:Expected\s+)?Time\s+Complexity\s*:\s*([^\n.]+)", page_text, re.I)
    space_match = re.search(
        r"(?:Expected\s+)?(?:Auxiliary\s+)?Space\s+Complexity\s*:\s*([^\n.]+)",
        page_text,
        re.I,
    ) or re.search(r"Auxiliary\s+Space\s*:\s*([^\n.]+)", page_text, re.I)
    return {
        "time": text(time_match.group(1)) if time_match else "",
        "space": text(space_match.group(1)) if space_match else "",
    }


def scrape_gfg(url: str, serial: int = 1) -> dict[str, Any]:
    problem_slug = gfg_problem_slug(url)
    if problem_slug:
        api_data = gfg_problem_api(problem_slug)
        if api_data:
            return scrape_gfg_practice(api_data, serial)

    response = requests.get(
        clean_url(url),
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        timeout=REQUEST_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    practice_data = gfg_practice_data(soup)
    if practice_data:
        return scrape_gfg_practice(practice_data, serial)

    json_ld = extract_json_ld(soup)
    heading = soup.find("h1")
    title = text(heading.get_text(" ", strip=True) if heading else "")
    if not title:
        title = text(next((x.get("headline") for x in json_ld if x.get("headline")), ""))
    if not title:
        title = text((soup.title.string if soup.title else "").split(" - ")[0])

    article = (
        soup.select_one("article")
        or soup.select_one(".problem-statement")
        or soup.select_one(".entry-content")
        or soup.select_one(".text")
        or soup.select_one("main")
    )
    article_html = str(article or "")
    page_text = (article or soup).get_text("\n", strip=True)

    difficulty_match = re.search(r"Difficulty\s*:\s*(Basic|Easy|Medium|Hard)", page_text, re.I)
    difficulty = normalize_difficulty(difficulty_match.group(1) if difficulty_match else "")
    known_companies = {
        "Amazon", "Microsoft", "Google", "Adobe", "Flipkart", "Samsung",
        "Goldman Sachs", "Morgan Stanley", "Walmart", "Apple", "Meta",
    }
    topics = []
    for link in soup.select('a[href*="/tag/"], a[href*="/category/"]'):
        value = text(link.get_text(" ", strip=True))
        if value and value not in known_companies and len(value) < 40 and value not in topics:
            topics.append(value)
    topics = topics[:4]
    companies = []
    for link in soup.select('a[href*="/tag/"]'):
        value = text(link.get_text(" ", strip=True))
        if value in known_companies and value not in companies:
            companies.append(value)

    description = ""
    for item in json_ld:
        if item.get("description"):
            description = problem_description(html.unescape(str(item["description"])))
            break
    if not description and article:
        paragraphs = [text(p.get_text(" ", strip=True)) for p in article.find_all("p")]
        description = problem_description("\n".join(p for p in paragraphs[:4] if p))

    code = ""
    for block in soup.select("pre, code"):
        candidate = block.get_text("\n", strip=False)
        if "class Solution" in candidate and "def " in candidate:
            code = candidate
            break

    record = blank_record(serial)
    record.update(
        {
            "titleSlug": slugify(title),
            "title": title,
            "content": description,
            "difficulty": difficulty,
            "topics": topics,
            "companies": companies[:],
            "examples": parse_examples_from_html(article_html),
            "constraints": parse_constraints(article_html),
            "starterCode": code,
            "topic": primary_topic(topics),
            "problem": title,
            "marks": difficulty_marks(difficulty),
            "expectedComplexity": find_complexity(page_text),
        }
    )
    return record


def scrape_problem(url: str, serial: int = 1) -> dict[str, Any]:
    platform = detect_platform(url)
    if platform == "leetcode":
        return scrape_leetcode(url, serial)
    return scrape_gfg(url, serial)


def parse_url_input(value: Any) -> list[str]:
    """Accept a URL list, pasted JSON array/object, or newline/comma-separated text."""
    if isinstance(value, dict):
        value = value.get("urls", value.get("url", []))
    if isinstance(value, list):
        return [text(item) for item in value if isinstance(item, str) and text(item)]
    raw = str(value or "").strip()
    if not raw:
        return []
    if raw.startswith(("[", "{")):
        try:
            return parse_url_input(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise ScrapeError(f"Invalid URL JSON: {exc.msg}.") from exc
    return [text(item) for item in re.split(r"[\n,]+", raw) if text(item)]


def read_sheet_names() -> list[str]:
    try:
        value = json.loads(SHEETS_FILE.read_text(encoding="utf-8"))
        return sorted(text(name) for name in value if text(name)) if isinstance(value, dict) else []
    except (OSError, json.JSONDecodeError):
        return []


def attach_sheet(record: dict[str, Any], sheet_name: str) -> None:
    record["sheetName"] = sheet_name
    record["sheetNames"] = [sheet_name]
    record["sheetIds"] = [slugify(sheet_name)]


def read_saved() -> list[dict[str, Any]]:
    if not OUTPUT_FILE.exists():
        return []
    try:
        value = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except json.JSONDecodeError:
        raise ScrapeError(f"{OUTPUT_FILE.name} is not valid JSON.")


def normalize_serial_ids(records: list[dict[str, Any]]) -> None:
    """Reassign question_serial_number and questionId to be sequential and gap-free."""
    for i, record in enumerate(records, start=1):
        record["question_serial_number"] = i
        record["questionId"] = i


def merge_sheet_info(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
    """
    Merge sheet metadata from ``incoming`` into ``existing`` in-place.

    Returns True if anything changed (i.e. the incoming record brought new
    sheet info that was not already present on the existing record).
    """
    # --- sheetIds (the slugified list) ---
    existing_ids: list[str] = list(existing.get("sheetIds") or [])
    incoming_ids: list[str] = list(incoming.get("sheetIds") or [])
    new_ids = [sid for sid in incoming_ids if sid not in existing_ids]

    # --- sheetNames (human-readable list) ---
    # Back-fill sheetNames on old records that only have sheetName (string).
    existing_names: list[str] = list(existing.get("sheetNames") or [])
    if not existing_names and existing.get("sheetName"):
        existing_names = [existing["sheetName"]]

    incoming_names: list[str] = list(incoming.get("sheetNames") or [])
    if not incoming_names and incoming.get("sheetName"):
        incoming_names = [incoming["sheetName"]]

    new_names = [name for name in incoming_names if name not in existing_names]

    if not new_ids and not new_names:
        return False  # nothing to merge

    existing["sheetIds"] = existing_ids + new_ids
    existing["sheetNames"] = existing_names + new_names
    # Keep sheetName (the primary string field) as the first entry for
    # backwards compatibility with any code that still reads it directly.
    existing["sheetName"] = existing["sheetNames"][0] if existing["sheetNames"] else ""
    existing["updatedAt"] = iso_now()
    return True


def save_record(record: dict[str, Any]) -> tuple[int, bool]:
    results = save_records([record])
    return results[0]["serial"], results[0]["replaced"]


def save_records(records_to_save: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Insert or merge multiple records, then persist the collection once.

    Rules
    -----
    * Uniqueness key  : ``titleSlug`` (case-insensitive, whitespace-stripped).
    * Duplicate in file : merge sheet info only; keep all other existing fields
      intact and preserve the original ``questionId`` / ``question_serial_number``.
    * Duplicate in batch : if the same slug appears more than once in the
      incoming batch, later entries are merged into the earlier one in-place
      before the file is touched.
    * IDs : ``question_serial_number`` and ``questionId`` are always a
      contiguous 1-based sequence with no gaps; they are rebuilt on every load
      so stale values from disk can never corrupt future inserts.
    """
    records = read_saved()

    # Rebuild sequential IDs on every load so gaps / duplicates from manual
    # edits or previous bugs are healed before any new records are appended.
    normalize_serial_ids(records)

    # Build a fast lookup: titleSlug -> index in ``records``.
    slug_index: dict[str, int] = {
        text(r.get("titleSlug")).lower(): i for i, r in enumerate(records)
    }

    results: list[dict[str, Any]] = []

    for record in records_to_save:
        slug = text(record.get("titleSlug"))
        slug_key = slug.lower()

        # Check for a duplicate inside the current batch first (before the
        # file), so two URLs pointing to the same problem in one submission
        # are merged together rather than one overwriting the other.
        batch_idx = slug_index.get(slug_key)

        if batch_idx is None:
            # Brand-new problem — assign the next serial.
            serial = len(records) + 1
            record["question_serial_number"] = serial
            record["questionId"] = serial
            records.append(record)
            slug_index[slug_key] = len(records) - 1
            results.append(
                {"serial": serial, "replaced": False, "merged": False, "titleSlug": slug}
            )
        else:
            existing = records[batch_idx]
            serial = existing["questionId"]  # preserve the original ID

            # Merge sheet metadata; only flag as merged when something new arrived.
            sheet_changed = merge_sheet_info(existing, record)

            results.append(
                {"serial": serial, "replaced": True, "merged": sheet_changed, "titleSlug": slug}
            )

    # One write, regardless of batch size.
    OUTPUT_FILE.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # Verify the write is valid JSON before returning success.
    json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    return results


PAGE = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>DSA Problem Scraper</title>
  <style>
    :root{color-scheme:dark}body{font:16px system-ui;margin:0;background:#0d1117;color:#e6edf3}
    main{max-width:1050px;margin:42px auto;padding:0 20px}h1{margin-bottom:8px}
    p{color:#9da7b3}.row{display:flex;gap:10px;align-items:stretch}.urls{flex:1;height:92px;margin:0}
    input,button,textarea{font:inherit;border:1px solid #30363d;border-radius:8px;padding:12px;background:#161b22;color:#e6edf3}
    button{cursor:pointer;background:#238636;border-color:#2ea043;font-weight:650}button.secondary{background:#1f6feb}
    textarea{box-sizing:border-box;width:100%;height:560px;margin-top:18px;font:13px ui-monospace,monospace;line-height:1.45}
    .actions{display:flex;gap:10px;margin:10px 0;align-items:center;flex-wrap:wrap}.file-label{cursor:pointer;background:#30363d;border-radius:8px;padding:10px 14px;font-weight:650}
    .sheet{min-width:280px}.field-label{color:#c9d1d9;font-weight:650}
    #status{min-height:24px;margin:14px 0;color:#79c0ff}.error{color:#ff7b72!important}.warn{color:#e3b341!important}
  </style>
</head>
<body><main>
  <h1>DSA Problem Scraper</h1>
  <p>Paste URLs one per line, paste a JSON URL array, or import a .json file.</p>
  <div class="actions">
    <label class="file-label">Import URL JSON<input id="jsonFile" type="file" accept=".json,application/json" hidden></label>
    <label class="field-label" for="sheet">Whose sheet are these questions from?</label>
    <input class="sheet" id="sheet" list="sheetNames" placeholder="e.g. Love Babbar DSA" required>
    <datalist id="sheetNames">
      {% for sheet_name in sheet_names %}<option value="{{ sheet_name }}">{% endfor %}
    </datalist>
  </div>
  <div class="row">
    <textarea class="urls" id="urls" placeholder='One URL per line, or: ["https://leetcode.com/problems/two-sum/", "https://leetcode.com/problems/valid-parentheses/"]' autofocus></textarea>
    <button id="scrape">Generate JSON</button>
    <button id="save" class="secondary" disabled>Save / update</button>
  </div>
  <div id="status"></div>
  <textarea id="output" spellcheck="false" placeholder="Generated JSON appears here"></textarea>
<script>
let current=null;
const status=document.querySelector('#status'), output=document.querySelector('#output');
document.querySelector('#jsonFile').onchange=async event=>{
  const file=event.target.files[0];if(!file)return;
  try{
    const raw=await file.text(), parsed=JSON.parse(raw);
    const urls=Array.isArray(parsed)?parsed:parsed.urls;
    if(!Array.isArray(urls)||!urls.every(url=>typeof url==='string'))throw new Error('JSON must be a URL array or an object containing a urls array.');
    document.querySelector('#urls').value=JSON.stringify(urls,null,2);
    status.className='';status.textContent=`Imported ${urls.length} URL(s). Click Generate JSON.`;
  }catch(e){status.className='error';status.textContent=`Could not import JSON: ${e.message}`}
  event.target.value='';
};
document.querySelector('#scrape').onclick=async()=>{
  status.className='';status.textContent='Scraping source…';current=null;
  document.querySelector('#save').disabled=true;
  try{
    const sheet=document.querySelector('#sheet').value.trim();
    if(!sheet)throw new Error('Choose or enter the sheet name first.');
    const r=await fetch('/api/scrape',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({urls:document.querySelector('#urls').value,sheet})});
    const data=await r.json();if(!r.ok)throw new Error(data.error||'Scrape failed');
    current=data.problems;output.value=JSON.stringify(current,null,2);
    status.textContent=`Generated ${data.problems.length} problem(s)${data.errors.length?`; ${data.errors.length} failed`:''}. Review, then save.`;
    document.querySelector('#save').disabled=false;
  }catch(e){status.className='error';status.textContent=e.message}
};
document.querySelector('#save').onclick=async()=>{
  try{
    current=JSON.parse(output.value);status.className='';status.textContent='Saving…';
    const r=await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({problems:Array.isArray(current)?current:[current]})});
    const data=await r.json();if(!r.ok)throw new Error(data.error||'Save failed');
    const parts=[`Saved ${data.saved} problem(s) to ${data.file}.`];
    if(data.added>0) parts.push(`${data.added} new.`);
    if(data.merged>0){status.className='warn';parts.push(`${data.merged} already existed — new sheet IDs appended.`);}
    else if(data.replaced>0) parts.push(`${data.replaced} updated.`);
    status.textContent=parts.join(' ');
  }catch(e){status.className='error';status.textContent=e.message}
};
</script></main></body></html>
"""


@app.get("/")
def index():
    return render_template_string(PAGE, sheet_names=read_sheet_names())


@app.post("/api/scrape")
def api_scrape():
    payload = request.get_json(silent=True) or {}
    raw_urls = payload.get("urls", payload.get("url", ""))
    try:
        urls = parse_url_input(raw_urls)
    except ScrapeError as exc:
        return jsonify({"error": str(exc)}), 400
    if not urls:
        return jsonify({"error": "At least one problem URL is required."}), 400
    sheet_name = text(payload.get("sheet"))
    if not sheet_name:
        return jsonify({"error": "Choose or enter whose sheet these questions belong to."}), 400

    problems, errors = [], []
    start_serial = len(read_saved()) + 1
    for url in urls:
        try:
            platform = detect_platform(url)
            problem = scrape_problem(url, start_serial + len(problems))
            attach_sheet(problem, sheet_name)
            problems.append(problem)
        except (ScrapeError, requests.RequestException) as exc:
            errors.append({"url": url, "error": str(exc)})
    if not problems:
        message = errors[0]["error"] if len(errors) == 1 else "No problems could be scraped."
        return jsonify({"error": message, "errors": errors}), 400

    response = {"problems": problems, "errors": errors}
    if len(urls) == 1:
        response.update({"platform": detect_platform(urls[0]), "problem": problems[0]})
    return jsonify(response)


@app.post("/api/save")
def api_save():
    payload = request.get_json(silent=True) or {}
    problems = payload.get("problems")
    if problems is None:
        problems = [payload.get("problem")]
    if (
        not isinstance(problems, list)
        or not problems
        or any(not isinstance(item, dict) or not text(item.get("titleSlug")) for item in problems)
    ):
        return jsonify({"error": "One or more generated problems with titleSlug are required."}), 400
    try:
        results = save_records(problems)
        added   = sum(1 for r in results if not r["replaced"])
        merged  = sum(1 for r in results if r["replaced"] and r["merged"])
        updated = sum(1 for r in results if r["replaced"] and not r["merged"])
        response = {
            "ok": True,
            "saved": len(results),
            "added": added,
            "merged": merged,
            "replaced": updated,
            "results": results,
            "file": OUTPUT_FILE.name,
        }
        if len(results) == 1:
            response["serial"] = results[0]["serial"]
        return jsonify(response)
    except ScrapeError as exc:
        return jsonify({"error": str(exc)}), 400


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5051, debug=False)