"""
setup_schema.py
---------------
Non-destructive schema setup for the 450-DSA MongoDB database.

Performs:
  1. Fixes duplicate titleSlugs on the `question` collection (appends -N suffix)
  2. Creates all required indexes across every collection
  3. Backfills missing default fields on existing documents

Run once:  python setup_schema.py
"""

import os
import sys
from datetime import datetime, timezone
from pymongo import MongoClient, ASCENDING, DESCENDING, TEXT

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME   = os.getenv("MONGO_DB_NAME", "450_dsa")

client = MongoClient(MONGO_URI)
db     = client[DB_NAME]

now = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 1. Fix duplicate titleSlugs before creating the unique index
# ---------------------------------------------------------------------------
def fix_duplicate_title_slugs():
    print("\n[1] Checking for duplicate titleSlugs ...")
    pipeline = [
        {"$group": {
            "_id": "$titleSlug",
            "count": {"$sum": 1},
            "ids": {"$push": "$_id"}
        }},
        {"$match": {"count": {"$gt": 1}}}
    ]
    dupes = list(db.question.aggregate(pipeline))
    if not dupes:
        print("    No duplicates found.")
        return

    for grp in dupes:
        slug = grp["_id"]
        ids  = grp["ids"][1:]          # keep the first, rename the rest
        print(f"    Fixing duplicate slug '{slug}' ({len(ids)+1} copies)")
        for i, oid in enumerate(ids, start=2):
            new_slug = f"{slug}-{i}"
            db.question.update_one({"_id": oid}, {"$set": {"titleSlug": new_slug}})
            print(f"      -> renamed _id={oid} to '{new_slug}'")

    print("    Duplicate slugs fixed.")


# ---------------------------------------------------------------------------
# 2. Create all indexes
# ---------------------------------------------------------------------------
def create_indexes():
    print("\n[2] Creating indexes ...")

    # ---- question ----
    q = db.question
    q.create_index([("questionId", ASCENDING)],  unique=True,  name="questionId_1",   background=True)
    q.create_index([("titleSlug",  ASCENDING)],  unique=True,  name="titleSlug_1",    background=True)
    q.create_index([("topic",      ASCENDING)],               name="topic_1",         background=True)
    q.create_index([("difficulty", ASCENDING)],               name="difficulty_1",    background=True)
    q.create_index([("topics",     ASCENDING)],               name="topics_1",        background=True)
    q.create_index([("companies",  ASCENDING)],               name="companies_1",     background=True)
    q.create_index([("status",     ASCENDING)],               name="status_1",        background=True)
    q.create_index([("title",      TEXT)],                    name="title_text",      background=True)
    # Compound for tracker look-up (legacy compatibility)
    q.create_index([("topic", ASCENDING), ("problem", ASCENDING), ("url", ASCENDING)],
                   unique=True, name="topic_problem_url", background=True,
                   sparse=True)
    print("    question: OK")

    # ---- topic ----
    t = db.topic
    t.create_index([("name",     ASCENDING)], unique=True, name="name_1",     background=True)
    t.create_index([("position", ASCENDING)],              name="position_1", background=True)
    print("    topic: OK")

    # ---- sheet ----
    s = db.sheet
    s.create_index([("sheetId", ASCENDING)], unique=True, name="sheetId_1", background=True)
    s.create_index([("name",    ASCENDING)],              name="name_1",    background=True)
    print("    sheet: OK")

    # ---- user ----
    u = db.user
    u.create_index([("email",     ASCENDING)], unique=True, sparse=True, name="email_1",     background=True)
    u.create_index([("github_id", ASCENDING)], unique=True, sparse=True, name="github_id_1", background=True)
    u.create_index([("google_id", ASCENDING)], unique=True, sparse=True, name="google_id_1", background=True)
    u.create_index([("is_admin",  ASCENDING)],                            name="is_admin_1",  background=True)
    print("    user: OK")

    # ---- test_case ----
    tc = db.test_case
    tc.create_index([("questionId", ASCENDING)], unique=True, name="questionId_1", background=True)
    print("    test_case: OK")

    # ---- user_sheet_progress ----
    usp = db.user_sheet_progress
    usp.create_index(
        [("userId", ASCENDING), ("sheetId", ASCENDING), ("questionId", ASCENDING)],
        unique=True, name="userId_sheetId_questionId", background=True
    )
    usp.create_index([("userId",     ASCENDING)], name="userId_1",     background=True)
    usp.create_index([("sheetId",    ASCENDING)], name="sheetId_1",    background=True)
    usp.create_index([("questionId", ASCENDING)], name="questionId_1", background=True)
    usp.create_index([("status",     ASCENDING)], name="status_1",     background=True)
    usp.create_index([("updatedAt",  DESCENDING)], name="updatedAt_-1", background=True)
    print("    user_sheet_progress: OK")

    # ---- submissions ----
    sub = db.submissions
    sub.create_index([("user_id",  ASCENDING)],  name="user_id_1",   background=True)
    sub.create_index([("q_id",     ASCENDING)],  name="q_id_1",      background=True)
    sub.create_index([("user_id",  ASCENDING), ("q_id", ASCENDING)],
                     name="user_id_q_id", background=True)
    sub.create_index([("status",    ASCENDING)], name="status_1",    background=True)
    sub.create_index([("timestamp", DESCENDING)], name="timestamp_-1", background=True)
    sub.create_index([("language",  ASCENDING)], name="language_1",  background=True)
    print("    submissions: OK")

    # ---- cohort ----
    c = db.cohort
    c.create_index([("join_code",  ASCENDING)], unique=True, name="join_code_1",  background=True)
    c.create_index([("created_by", ASCENDING)],              name="created_by_1", background=True)
    print("    cohort: OK")

    # ---- cohort_membership ----
    cm = db.cohort_membership
    # Drop conflicting old index name if present before re-creating
    try:
        existing_idx = {i["name"]: i for i in cm.list_indexes()}
        if "cohort_id_1_user_id_1" in existing_idx:
            cm.drop_index("cohort_id_1_user_id_1")
            print("    cohort_membership: dropped old index 'cohort_id_1_user_id_1'")
    except Exception as e:
        print(f"    cohort_membership: could not drop old index: {e}")
    cm.create_index(
        [("cohort_id", ASCENDING), ("user_id", ASCENDING)],
        unique=True, name="cohort_id_user_id", background=True
    )
    cm.create_index([("user_id", ASCENDING)], name="user_id_1", background=True)
    print("    cohort_membership: OK")

    print("    All indexes created.")


# ---------------------------------------------------------------------------
# 3. Backfill missing fields on existing documents
# ---------------------------------------------------------------------------
def backfill_questions():
    """Ensure every question document has all expected fields."""
    print("\n[3] Backfilling missing fields on `question` documents ...")

    default_stats = {
        "totalAccepted": 0,
        "totalSubmissions": 0,
        "acceptanceRate": 0.0,
        "likes": 0,
        "dislikes": 0,
    }

    result = db.question.update_many(
        {"questionId":       {"$exists": False}},
        {"$set": {"questionId": 0}}            # placeholder; real IDs set by migration
    )
    print(f"    Added missing questionId: {result.modified_count}")

    result = db.question.update_many(
        {"titleSlug":  {"$exists": False}},
        {"$set": {"titleSlug": ""}}
    )
    print(f"    Added missing titleSlug: {result.modified_count}")

    result = db.question.update_many(
        {"title":      {"$exists": False}},
        {"$set": {"title": ""}}
    )
    print(f"    Added missing title: {result.modified_count}")

    result = db.question.update_many(
        {"content":    {"$exists": False}},
        {"$set": {"content": ""}}
    )
    print(f"    Added missing content: {result.modified_count}")

    result = db.question.update_many(
        {"difficulty": {"$exists": False}},
        {"$set": {"difficulty": "Medium"}}
    )
    print(f"    Added missing difficulty: {result.modified_count}")

    result = db.question.update_many(
        {"topics":     {"$exists": False}},
        {"$set": {"topics": []}}
    )
    print(f"    Added missing topics: {result.modified_count}")

    result = db.question.update_many(
        {"companies":  {"$exists": False}},
        {"$set": {"companies": []}}
    )
    print(f"    Added missing companies: {result.modified_count}")

    result = db.question.update_many(
        {"examples":   {"$exists": False}},
        {"$set": {"examples": []}}
    )
    print(f"    Added missing examples: {result.modified_count}")

    result = db.question.update_many(
        {"constraints": {"$exists": False}},
        {"$set": {"constraints": []}}
    )
    print(f"    Added missing constraints: {result.modified_count}")

    result = db.question.update_many(
        {"similarQuestions": {"$exists": False}},
        {"$set": {"similarQuestions": []}}
    )
    print(f"    Added missing similarQuestions: {result.modified_count}")

    result = db.question.update_many(
        {"stats": {"$exists": False}},
        {"$set": {"stats": default_stats}}
    )
    print(f"    Added missing stats: {result.modified_count}")

    result = db.question.update_many(
        {"status":     {"$exists": False}},
        {"$set": {"status": "published"}}
    )
    print(f"    Added missing status: {result.modified_count}")

    result = db.question.update_many(
        {"marks": {"$exists": False}},
        {"$set": {"marks": 0}}
    )
    print(f"    Added missing marks: {result.modified_count}")

    result = db.question.update_many(
        {"hints":      {"$exists": False}},
        {"$set": {"hints": []}}
    )
    print(f"    Added missing hints: {result.modified_count}")

    result = db.question.update_many(
        {"editorial_links": {"$exists": False}},
        {"$set": {"editorial_links": []}}
    )
    print(f"    Added missing editorial_links: {result.modified_count}")

    result = db.question.update_many(
        {"createdAt":  {"$exists": False}},
        {"$set": {"createdAt": now}}
    )
    print(f"    Added missing createdAt: {result.modified_count}")

    result = db.question.update_many(
        {"updatedAt":  {"$exists": False}},
        {"$set": {"updatedAt": now}}
    )
    print(f"    Added missing updatedAt: {result.modified_count}")

    # Legacy fields kept for backward-compat with tracker routes
    result = db.question.update_many(
        {"url":  {"$exists": False}},
        {"$set": {"url": ""}}
    )
    print(f"    Added missing url (legacy): {result.modified_count}")

    result = db.question.update_many(
        {"url2": {"$exists": False}},
        {"$set": {"url2": ""}}
    )
    print(f"    Added missing url2 (legacy): {result.modified_count}")

    result = db.question.update_many(
        {"problem": {"$exists": False}},
        {"$set": {"problem": ""}}
    )
    print(f"    Added missing problem (legacy): {result.modified_count}")

    print("    question backfill complete.")


def backfill_users():
    """Ensure every user document has all expected fields."""
    print("\n[4] Backfilling missing fields on `user` documents ...")

    result = db.user.update_many(
        {"is_admin": {"$exists": False}},
        {"$set": {"is_admin": False}}
    )
    print(f"    Added missing is_admin: {result.modified_count}")

    result = db.user.update_many(
        {"progress": {"$exists": False}},
        {"$set": {"progress": {}}}
    )
    print(f"    Added missing progress: {result.modified_count}")

    result = db.user.update_many(
        {"profile_visibility": {"$exists": False}},
        {"$set": {"profile_visibility": "public"}}
    )
    print(f"    Added missing profile_visibility: {result.modified_count}")

    result = db.user.update_many(
        {"in_sheet_platform_counts": {"$exists": False}},
        {"$set": {"in_sheet_platform_counts": {
            "LeetCode": 0, "GFG": 0, "Coding Ninjas": 0,
            "HackerRank": 0, "AtCoder": 0, "Codewars": 0, "Other": 0
        }}}
    )
    print(f"    Added missing in_sheet_platform_counts: {result.modified_count}")

    result = db.user.update_many(
        {"dsa_progress": {"$exists": False}},
        {"$set": {"dsa_progress": 0.0}}
    )
    print(f"    Added missing dsa_progress: {result.modified_count}")

    result = db.user.update_many(
        {"current_streak": {"$exists": False}},
        {"$set": {"current_streak": 0}}
    )
    print(f"    Added missing current_streak: {result.modified_count}")

    result = db.user.update_many(
        {"longest_streak": {"$exists": False}},
        {"$set": {"longest_streak": 0}}
    )
    print(f"    Added missing longest_streak: {result.modified_count}")

    result = db.user.update_many(
        {"external_totals": {"$exists": False}},
        {"$set": {"external_totals": {}}}
    )
    print(f"    Added missing external_totals: {result.modified_count}")

    result = db.user.update_many(
        {"external_daily_counts": {"$exists": False}},
        {"$set": {"external_daily_counts": {}}}
    )
    print(f"    Added missing external_daily_counts: {result.modified_count}")

    result = db.user.update_many(
        {"platform_calendars": {"$exists": False}},
        {"$set": {"platform_calendars": {}}}
    )
    print(f"    Added missing platform_calendars: {result.modified_count}")

    print("    user backfill complete.")


def backfill_topics():
    """Ensure every topic document has all expected fields."""
    print("\n[5] Backfilling missing fields on `topic` documents ...")

    result = db.topic.update_many(
        {"started": {"$exists": False}},
        {"$set": {"started": False}}
    )
    print(f"    Added missing started: {result.modified_count}")

    result = db.topic.update_many(
        {"doneQuestions": {"$exists": False}},
        {"$set": {"doneQuestions": 0}}
    )
    print(f"    Added missing doneQuestions: {result.modified_count}")

    print("    topic backfill complete.")


def backfill_user_sheet_progress():
    """Ensure every user_sheet_progress document has all expected fields."""
    print("\n[6] Backfilling missing fields on `user_sheet_progress` documents ...")

    result = db.user_sheet_progress.update_many(
        {"status": {"$exists": False}},
        {"$set": {"status": "attempted"}}
    )
    print(f"    Added missing status: {result.modified_count}")

    result = db.user_sheet_progress.update_many(
        {"note": {"$exists": False}},
        {"$set": {"note": ""}}
    )
    print(f"    Added missing note: {result.modified_count}")

    result = db.user_sheet_progress.update_many(
        {"revision_status": {"$exists": False}},
        {"$set": {"revision_status": "To Review"}}
    )
    print(f"    Added missing revision_status: {result.modified_count}")

    result = db.user_sheet_progress.update_many(
        {"bookmarked": {"$exists": False}},
        {"$set": {"bookmarked": False}}
    )
    print(f"    Added missing bookmarked: {result.modified_count}")

    result = db.user_sheet_progress.update_many(
        {"updatedAt": {"$exists": False}},
        {"$set": {"updatedAt": now}}
    )
    print(f"    Added missing updatedAt: {result.modified_count}")

    print("    user_sheet_progress backfill complete.")


def backfill_submissions():
    """Ensure every submission document has all expected fields."""
    print("\n[7] Backfilling missing fields on `submissions` documents ...")

    result = db.submissions.update_many(
        {"note": {"$exists": False}},
        {"$set": {"note": ""}}
    )
    print(f"    Added missing note: {result.modified_count}")

    result = db.submissions.update_many(
        {"language": {"$exists": False}},
        {"$set": {"language": "Unknown"}}
    )
    print(f"    Added missing language: {result.modified_count}")

    result = db.submissions.update_many(
        {"runtime": {"$exists": False}},
        {"$set": {"runtime": "0 ms"}}
    )
    print(f"    Added missing runtime: {result.modified_count}")

    result = db.submissions.update_many(
        {"memory": {"$exists": False}},
        {"$set": {"memory": "0.00 MB"}}
    )
    print(f"    Added missing memory: {result.modified_count}")

    result = db.submissions.update_many(
        {"passed": {"$exists": False}},
        {"$set": {"passed": 0}}
    )
    print(f"    Added missing passed: {result.modified_count}")

    result = db.submissions.update_many(
        {"total": {"$exists": False}},
        {"$set": {"total": 0}}
    )
    print(f"    Added missing total: {result.modified_count}")

    result = db.submissions.update_many(
        {"timestamp": {"$exists": False}},
        {"$set": {"timestamp": now}}
    )
    print(f"    Added missing timestamp: {result.modified_count}")

    print("    submissions backfill complete.")


def print_summary():
    print("\n" + "="*60)
    print("SCHEMA SETUP COMPLETE")
    print("="*60)
    print(f"  questions          : {db.question.count_documents({})}")
    print(f"  topics             : {db.topic.count_documents({})}")
    print(f"  sheets             : {db.sheet.count_documents({})}")
    print(f"  users              : {db.user.count_documents({})}")
    print(f"  user_sheet_progress: {db.user_sheet_progress.count_documents({})}")
    print(f"  submissions        : {db.submissions.count_documents({})}")
    print(f"  cohorts            : {db.cohort.count_documents({})}")
    print(f"  cohort_members     : {db.cohort_membership.count_documents({})}")
    print()
    print("Indexes per collection:")
    for col in ["question","topic","sheet","user","user_sheet_progress","submissions","cohort","cohort_membership"]:
        idx_names = [i["name"] for i in db[col].list_indexes()]
        print(f"  {col}: {idx_names}")


if __name__ == "__main__":
    print(f"Connecting to {MONGO_URI} -> {DB_NAME}")
    fix_duplicate_title_slugs()
    create_indexes()
    backfill_questions()
    backfill_users()
    backfill_topics()
    backfill_user_sheet_progress()
    backfill_submissions()
    print_summary()
