"""
app/sheet/routes.py
-------------------
Sheet listing and question view — all data served from MongoDB.

Route map:
  GET /sheet/                        → list all sheets from `sheet` collection
  GET /sheet/<sheet_id>              → view questions for a sheet
  GET /sheet/<sheet_id>/<q_slug>     → redirect to practice page for a question
"""

from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_login import current_user
from bson import ObjectId

from app.extensions import db
from app.practice.routes import load_progress

sheet_bp = Blueprint("sheet", __name__, url_prefix="/sheet")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9-]", "-", text.lower().strip()).strip("-")


def _load_user_progress(user_id) -> dict:
    """Return a {q_id_str: progress_dict} map for the current user."""
    try:
        return load_progress(user_id)
    except Exception:
        return {}


def _diff_short(difficulty: str) -> str:
    mapping = {"easy": "Easy", "medium": "Med.", "hard": "Hard"}
    return mapping.get(str(difficulty).lower(), "Med.")


def _acceptance_from_stats(question_doc: dict) -> str:
    """Compute acceptance rate from this app's own submission stats."""
    stats = question_doc.get("stats") or {}
    total = stats.get("totalSubmissions", 0) or 0
    accepted = stats.get("totalAccepted", 0) or 0
    if total > 0:
        return f"{(accepted / total) * 100:.1f}%"
    return "0.0%"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@sheet_bp.route("/")
def list_sheets():
    """List all sheets from the `sheet` collection."""
    sheet_name = request.args.get("sheet")
    if sheet_name:
        # Legacy ?sheet=Name redirect
        return redirect(url_for("sheet.sheet_view", sheet_id=_slugify(sheet_name)))

    sheets_cursor = db.sheet.find(
        {},
        {
            "name": 1,
            "sheetId": 1,
            "description": 1,
            "totalQuestions": 1,
            "author": 1,
            "tags": 1,
        },
    ).sort("name", 1)

    sheets = []
    for s in sheets_cursor:
        sheets.append({
            "name":           s.get("name") or s.get("sheetId", "Unnamed"),
            "slug":           s.get("sheetId") or _slugify(s.get("name", "")),
            "description":    s.get("description", ""),
            "total":          s.get("totalQuestions", 0),
            "author":         s.get("author", ""),
            "tags":           s.get("tags", []),
        })

    return render_template("sheet/list.html", sheets=sheets)


@sheet_bp.route("/<sheet_id>", endpoint="sheet_view")
def sheet_view(sheet_id: str):
    """
    Show all questions belonging to a sheet.

    Lookup order:
      1. sheet.sheetId == sheet_id   (primary — slug-based)
      2. sheet._id == ObjectId        (fallback — for very old URLs)
    """
    sheet_doc = db.sheet.find_one({"sheetId": sheet_id})
    if not sheet_doc:
        # Try ObjectId fallback
        try:
            sheet_doc = db.sheet.find_one({"_id": ObjectId(sheet_id)})
        except Exception:
            pass
    if not sheet_doc:
        abort(404)

    sheet_name  = sheet_doc.get("name") or sheet_id
    sheet_slug  = sheet_doc.get("sheetId") or sheet_id

    # ----------------------------------------------------------------
    # Fetch questions — two strategies:
    #   A) If the sheet doc has an embedded `questionIds` list → use it
    #   B) Otherwise fall back to topic-based lookup (legacy sheets)
    # ----------------------------------------------------------------
    raw_questions = []

    question_ids = sheet_doc.get("questionIds") or []
    if question_ids:
        # Strategy A: explicit list stored on the sheet
        raw_questions = list(
            db.question.find(
                {"_id": {"$in": [ObjectId(qid) if not isinstance(qid, ObjectId) else qid
                                  for qid in question_ids]}},
                {"title": 1, "titleSlug": 1, "difficulty": 1, "topics": 1,
                 "companies": 1, "stats": 1, "questionId": 1, "url": 1,
                 "problem": 1, "status": 1, "sheetOrder": 1},
            )
        )
    else:
        # Strategy B: the sheet name matches a topic name in `topic` collection,
        # or we just look up all questions whose `topics` array contains the sheet name.
        # This covers the legacy Love Babbar / imported sheets.
        topic_doc = db.topic.find_one(
            {"topicName": {"$regex": f"^{sheet_name}$", "$options": "i"}},
            {"_id": 1},
        )
        if topic_doc:
            raw_questions = list(
                db.question.find(
                    {"topic": topic_doc["_id"]},
                    {"title": 1, "titleSlug": 1, "difficulty": 1, "topics": 1,
                     "companies": 1, "stats": 1, "questionId": 1, "url": 1,
                     "problem": 1, "status": 1, "sheetOrder": 1},
                )
            )
        else:
            # Fallback for new schema: Since Love Babbar questions don't have "Love Babbar" as a topic,
            # we query questions that have this sheet's ID implicitly stored in an array.
            raw_questions = list(
                db.question.find(
                    {"sheetIds": sheet_slug},
                    {"title": 1, "titleSlug": 1, "difficulty": 1, "topics": 1,
                     "companies": 1, "stats": 1, "questionId": 1, "url": 1,
                     "problem": 1, "status": 1, "sheetOrder": 1},
                )
            )

    # ----------------------------------------------------------------
    # User progress
    # ----------------------------------------------------------------
    progress = {}
    if current_user.is_authenticated:
        progress = _load_user_progress(current_user.id)

    # ----------------------------------------------------------------
    # Build question list for the template
    # ----------------------------------------------------------------
    questions = []
    for idx, q in enumerate(raw_questions, start=1):
        q_id    = str(q.get("questionId") or q["_id"])
        title   = q.get("title") or q.get("problem") or "Untitled"
        tslug   = q.get("titleSlug") or _slugify(title)
        diff    = _diff_short(q.get("difficulty", "Medium"))
        acc     = _acceptance_from_stats(q)
        sort_order = (q.get("sheetOrder") or {}).get(sheet_slug) or idx

        q_prog  = progress.get(q_id, {})

        is_bookmarked = False
        if "bookmarked_sheets" in q_prog:
            is_bookmarked = sheet_slug in q_prog["bookmarked_sheets"]
        else:
            is_bookmarked = q_prog.get("bookmark", False)

        questions.append({
            "id":         q.get("questionId") or idx,
            "display_id": sort_order,
            "sort_order": sort_order,
            "mongo_id":   str(q["_id"]),
            "title":      title,
            "slug":       tslug,
            "difficulty": diff,
            "acceptance": acc,
            "topics":     q.get("topics", []),
            "companies":  q.get("companies", []),
            "completed":  q_prog.get("done", False),
            "bookmarked": is_bookmarked,
        })

    # Sort by sheet-specific order when present; fall back to questionId.
    questions.sort(
        key=lambda q: (
            int(q["sort_order"]) if str(q["sort_order"]).isdigit() else 10**9,
            int(q["id"]) if str(q["id"]).isdigit() else 0,
        )
    )

    total_solved = sum(1 for q in questions if q["completed"])

    return render_template(
        "sheet/view.html",
        sheet_name=sheet_name,
        sheet_slug=sheet_slug,
        questions=questions,
        total_solved=total_solved,
        total=len(questions),
    )


@sheet_bp.route("/<sheet_id>/<q_slug>", endpoint="sheet_practice_redirect")
def sheet_practice_redirect(sheet_id: str, q_slug: str):
    """Redirect to the practice page for a specific question in a sheet."""
    # Find the question by its titleSlug
    q_doc = db.question.find_one(
        {"titleSlug": q_slug},
        {"_id": 1, "questionId": 1, "title": 1},
    )
    if not q_doc:
        # Fallback: search by slugified title
        q_doc = db.question.find_one(
            {"title": {"$regex": q_slug.replace("-", " "), "$options": "i"}},
            {"_id": 1, "questionId": 1, "title": 1},
        )
    if not q_doc:
        abort(404)

    q_id = str(q_doc.get("questionId") or q_doc["_id"])
    return redirect(url_for("practice.practice_view", q_id=q_slug, sheet_slug=sheet_id))
