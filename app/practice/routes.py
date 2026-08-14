from flask import Blueprint, render_template, request, jsonify
from flask_login import current_user, login_required
import os
import json
import datetime
from bson.objectid import ObjectId
from app.extensions import db
from app.practice.core.executor import run_code
from app.practice.core.question_manager import get_patterns, BANK_DIR, WORKSPACE_DIR

from bson.objectid import ObjectId

practice_bp = Blueprint('practice', __name__, url_prefix='/practice')

SHEETS_FILE = os.path.join(BANK_DIR, 'sheets.json')
SOLUTION_FILE = os.path.join(WORKSPACE_DIR, 'solution.txt')

def load_progress(user_id):
    user = db.user.find_one({"_id": ObjectId(user_id)})
    if user and "progress" in user:
        prog = user["progress"]
        normalized = {}
        for k, v in prog.items():
            if isinstance(v, bool):
                normalized[k] = {"done": v}
            else:
                normalized[k] = v
        return normalized
    return {}

def save_progress(user_id, data):
    db.user.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"progress": data}}
    )

@practice_bp.route('/')
@practice_bp.route('/<sheet_slug>/<q_id>', endpoint='practice_view')
def index(sheet_slug=None, q_id=None):
    return render_template('practice/index.html', sheet_slug=sheet_slug, q_id=q_id)

@practice_bp.route('/api/init', methods=['GET'])
def get_init_data():
    progress = {}
    if current_user.is_authenticated:
        progress = load_progress(current_user.id)
    
    sheets_cursor = db.sheet.find({}, {"name": 1, "sheetId": 1})
    enhanced_sheets = {}
    
    for s in sheets_cursor:
        sheet_slug = s.get("sheetId")
        sheet_name = s.get("name")
        enhanced_sheets[sheet_slug] = []
        
        # Get all questions for this sheet
        raw_questions = []
        question_ids = s.get("questionIds") or []
        if question_ids:
            # Strategy A: explicit list stored on the sheet
            raw_questions = list(db.question.find(
                {"_id": {"$in": [ObjectId(qid) if not isinstance(qid, ObjectId) else qid for qid in question_ids]}},
                {"questionId": 1, "title": 1, "titleSlug": 1, "difficulty": 1, "sheetOrder": 1}
            ))
        else:
            # Strategy B: topic lookup
            topic_doc = db.topic.find_one(
                {"topicName": {"$regex": f"^{sheet_name}$", "$options": "i"}},
                {"_id": 1},
            )
            if topic_doc:
                raw_questions = list(db.question.find(
                    {"topic": topic_doc["_id"]},
                    {"questionId": 1, "title": 1, "titleSlug": 1, "difficulty": 1, "sheetOrder": 1}
                ))
            else:
                # Strategy C: topics string match fallback or sheetIds
                raw_questions = list(db.question.find(
                    {"$or": [
                        {"topics": {"$regex": sheet_name, "$options": "i"}},
                        {"sheetIds": sheet_slug},
                    ]},
                    {"questionId": 1, "title": 1, "titleSlug": 1, "difficulty": 1, "sheetOrder": 1}
                ))
        
        # Sort questions
        raw_questions.sort(
            key=lambda q: (
                int((q.get("sheetOrder") or {}).get(sheet_slug) or 10**9),
                int(q.get("questionId") or 0),
            )
        )
        
        for q in raw_questions:
            q_id = str(q.get("questionId"))
            
            q_prog = progress.get(q_id, {})
            is_completed = q_prog.get("done", False)
            
            enhanced_sheets[sheet_slug].append({
                "id": q_id,
                "category": sheet_slug,
                "name": q.get("title", ""),
                "slug": q.get("titleSlug", ""),
                "difficulty": q.get("difficulty", "Medium"),
                "completed": is_completed
            })

    return jsonify({"sheets": enhanced_sheets})

@practice_bp.route('/api/question/<category>/<q_id>', methods=['GET'])
def get_question(category, q_id):
    # Try to find by integer ID first, then by object ID or slug
    try:
        q_obj = db.question.find_one({"questionId": int(q_id)})
    except ValueError:
        q_obj = db.question.find_one({"titleSlug": q_id})
        
    if not q_obj:
        return jsonify({"error": "Question not found"}), 404

    # Extract metadata if available in DB
    metadata_db = q_obj.get("metadata", {})
    param_names = metadata_db.get("param_names", [])
    method_name = metadata_db.get("method_name", "")
    
    if not method_name:
        # Generate from titleSlug (e.g., 'two-sum' -> 'twoSum')
        slug_parts = q_obj.get("titleSlug", "").split("-")
        if slug_parts:
            method_name = slug_parts[0] + "".join(p.capitalize() for p in slug_parts[1:])
        else:
            method_name = "solve"
            
    if not param_names:
        # Try to parse from the first example's input
        import re
        examples = q_obj.get("examples", [])
        if examples and examples[0].get("input"):
            input_str = examples[0]["input"]
            matches = re.findall(r'([a-zA-Z_]\w*)\s*=', input_str)
            if matches:
                param_names = matches
            else:
                param_names = ["arg"]
        else:
            param_names = ["arg"]

    boilerplate = q_obj.get("boilerplate") or q_obj.get("starter_code")
    if not boilerplate:
        args_str = ", ".join(param_names)
        boilerplate = f"class Solution:\n    def {method_name}(self, {args_str}):\n        pass\n"

    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    with open(SOLUTION_FILE, 'w', encoding='utf-8') as f:
        f.write(boilerplate)
        
    # Translate DB structure to what frontend expects
    metadata = {
        "class_name": metadata_db.get("class_name", "Solution"),
        "method_name": method_name,
        "param_names": param_names,
        "test_cases": q_obj.get("examples", [])  # pass examples as test cases for now
    }
    
    q_info = {
        "id": q_obj.get("questionId", ""),
        "name": q_obj.get("title", ""),
        "titleSlug": q_obj.get("titleSlug", ""),
        "difficulty": q_obj.get("difficulty", "Medium"),
        "topics": q_obj.get("topics", []),
        "companies": q_obj.get("companies", []),
        "stats": q_obj.get("stats", {}),
        "similarQuestions": q_obj.get("similarQuestions", [])
    }

    return jsonify({
        "description": q_obj.get("content", ""),
        "constraints": q_obj.get("constraints", []),
        "examples": q_obj.get("examples", []),
        "boilerplate": boilerplate,
        "metadata": metadata,
        "param_names": param_names,
        "q_info": q_info,
        "expectedComplexity": q_obj.get("expectedComplexity", {})
    })

@practice_bp.route('/api/execute', methods=['POST'])
@login_required
def execute_code():
    data = request.json
    user_code = data.get('code', '')
    mode = data.get('mode', 'run')
    q_id = data.get('q_id')

    q_obj = db.question.find_one({"questionId": int(q_id)})
    if not q_obj:
        return jsonify({"status": "Error", "error_msg": "Question not found"}), 404

    if mode == 'submit':
        # Fetch the comprehensive test cases (both public and hidden) from the new collection
        tc_doc = db.test_case.find_one({"questionId": int(q_id)})
        if tc_doc and "test_cases" in tc_doc:
            test_cases = tc_doc["test_cases"]
        else:
            # Fallback to question examples if no specific test_case document is found
            test_cases = q_obj.get("examples", [])
    else:
        # Just run the ones the user passed in via the UI
        test_cases = data.get('test_cases', [])

    metadata = data.get('metadata')
    if not metadata:
        metadata_db = q_obj.get("metadata", {})
        method_name = metadata_db.get("method_name", "")
        if not method_name:
            slug_parts = q_obj.get("titleSlug", "").split("-")
            method_name = slug_parts[0] + "".join(p.capitalize() for p in slug_parts[1:]) if slug_parts else "solve"
        metadata = {
            "class_name": metadata_db.get("class_name", "Solution"),
            "method_name": method_name
        }

    # Save to workspace so local file watchers / IDEs stay in sync
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    with open(SOLUTION_FILE, 'w', encoding='utf-8') as f:
        f.write(user_code)

    success, payload = run_code(test_cases, metadata, user_code)

    if not success:
        return jsonify({
            "status": "Runtime Error",
            "error_msg": payload,
            "passed": 0,
            "total": len(test_cases)
        })

    results = payload["results"]
    runtime_ms = payload.get("runtime_ms", 0)
    memory_mb = payload.get("memory_mb", 0)
    
    runtime_str = f"{runtime_ms:.0f} ms" if runtime_ms else "0 ms"
    memory_str = f"{memory_mb:.2f} MB" if memory_mb else "0.00 MB"

    passed_count = sum(1 for r in results if r.get("pass"))
    
    first_failed = next((r for r in results if not r.get("pass")), None)
    if first_failed:
        first_failed["index"] = results.index(first_failed) + 1

    total = len(test_cases)
    if passed_count == total and total > 0:
        status = "Accepted"
    else:
        status = "Wrong Answer" if (first_failed and "error" not in first_failed) else "Runtime Error"

    response_data = {
        "status": status,
        "passed": passed_count,
        "total": total,
        "stdout": payload.get("stdout", ""),
        "stderr": payload.get("stderr", ""),
        "results": results,
        "runtime": runtime_str,
        "memory": memory_str
    }

    if status == "Accepted" and mode == "submit" and q_id:
        progress = load_progress(current_user.id)
        progress[q_id] = {"done": True}
        save_progress(current_user.id, progress)
        response_data["completed"] = True
        
        # Calculate percentiles (beats %)
        total_accepted = db.submissions.count_documents({"q_id": q_id, "status": "Accepted"})
        if total_accepted > 0:
            slower_count = db.submissions.count_documents({"q_id": q_id, "status": "Accepted", "runtime_ms": {"$gt": runtime_ms}})
            response_data["runtime_percentile"] = round((slower_count / total_accepted) * 100, 2)
            
            worse_mem_count = db.submissions.count_documents({"q_id": q_id, "status": "Accepted", "memory_mb": {"$gt": memory_mb}})
            response_data["memory_percentile"] = round((worse_mem_count / total_accepted) * 100, 2)
        else:
            response_data["runtime_percentile"] = 100.00
            response_data["memory_percentile"] = 100.00

    if mode == "submit" and q_id:
        # Increment question stats
        inc_fields = {"stats.totalSubmissions": 1}
        if status == "Accepted":
            inc_fields["stats.totalAccepted"] = 1
        
        db.question.update_one(
            {"questionId": int(q_id)},
            {"$inc": inc_fields}
        )
        
        # Recalculate acceptance rate
        updated_q = db.question.find_one({"questionId": int(q_id)}, {"stats": 1})
        if updated_q and "stats" in updated_q:
            stats_doc = updated_q["stats"]
            t_sub = stats_doc.get("totalSubmissions", 0)
            t_acc = stats_doc.get("totalAccepted", 0)
            if t_sub > 0:
                acc_rate = round((t_acc / t_sub) * 100, 2)
                db.question.update_one(
                    {"questionId": int(q_id)},
                    {"$set": {"stats.acceptanceRate": acc_rate}}
                )

        db.submissions.insert_one({
            "user_id": current_user.id,
            "q_id": q_id,
            "code": user_code,
            "status": status,
            "passed": passed_count,
            "total": total,
            "runtime": runtime_str,
            "memory": memory_str,
            "runtime_ms": runtime_ms,
            "memory_mb": memory_mb,
            "runtime_percentile": response_data.get("runtime_percentile", 0),
            "memory_percentile": response_data.get("memory_percentile", 0),
            "language": "Python 3",
            "note": "",
            "timestamp": datetime.datetime.utcnow()
        })

    return jsonify(response_data)

@practice_bp.route('/api/submissions/<q_id>', methods=['GET'])
@login_required
def get_submissions(q_id):
    submissions = list(db.submissions.find({"user_id": current_user.id, "q_id": q_id}).sort("timestamp", -1))
    for s in submissions:
        s["_id"] = str(s["_id"])
        s["user_id"] = str(s.get("user_id"))
        s["note"] = s.get("note", "")
        s["language"] = s.get("language", "Python 3")
        s["runtime_percentile"] = s.get("runtime_percentile", 0)
        s["memory_percentile"] = s.get("memory_percentile", 0)
    return jsonify({"submissions": submissions})

@practice_bp.route('/api/submissions/<sub_id>/note', methods=['PUT'])
@login_required
def update_submission_note(sub_id):
    data = request.json
    note = data.get('note', '')
    res = db.submissions.update_one(
        {"_id": ObjectId(sub_id), "user_id": current_user.id},
        {"$set": {"note": note}}
    )
    if res.modified_count == 1:
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Submission not found or permission denied"}), 404

@practice_bp.route('/api/solutions', methods=['POST'])
@login_required
def post_solution():
    data = request.json
    q_id = data.get('q_id')
    code = data.get('code')
    title = data.get('title')
    description = data.get('description', '')
    tags = data.get('tags', [])

    if not isinstance(tags, list):
        tags = []
    
    # ensure "Python 3" is always one of the tags to mirror LC behavior
    if "Python 3" not in tags:
        tags.append("Python 3")

    if not q_id or not code or not title:
        return jsonify({"success": False, "error": "Missing required fields"}), 400

    solution = {
        "user_id": current_user.id,
        "author_name": current_user.name,
        "q_id": q_id,
        "title": title,
        "code": code,
        "description": description,
        "upvotes": [],
        "downvotes": [],
        "views": 0,
        "tags": tags,
        "timestamp": datetime.datetime.utcnow()
    }
    db.solutions.insert_one(solution)
    return jsonify({"success": True})

@practice_bp.route('/api/solutions/<q_id>', methods=['GET'])
def get_solutions(q_id):
    # Retrieve solutions
    solutions = list(db.solutions.find({"q_id": q_id}))
    
    for s in solutions:
        s["_id"] = str(s["_id"])
        s["user_id"] = str(s.get("user_id"))
        
        upvotes = s.get("upvotes", [])
        if isinstance(upvotes, int): upvotes = []
        downvotes = s.get("downvotes", [])
        if isinstance(downvotes, int): downvotes = []
        
        s["upvote_count"] = len(upvotes)
        s["downvote_count"] = len(downvotes)
        s["views"] = s.get("views", 0)
        s["tags"] = s.get("tags", ["Python 3"])
        
        if current_user.is_authenticated:
            if current_user.id in upvotes:
                s["user_vote"] = "up"
            elif current_user.id in downvotes:
                s["user_vote"] = "down"
            else:
                s["user_vote"] = None
        else:
            s["user_vote"] = None
            
        # Clean up lists to save bandwidth
        s.pop("upvotes", None)
        s.pop("downvotes", None)

    # Sort by upvotes manually after resolving lengths
    solutions.sort(key=lambda x: x["upvote_count"], reverse=True)
    return jsonify({"solutions": solutions})

@practice_bp.route('/api/solutions/<sol_id>/vote', methods=['POST'])
@login_required
def vote_solution(sol_id):
    data = request.json
    action = data.get('action') # "up", "down", "none"
    
    sol = db.solutions.find_one({"_id": ObjectId(sol_id)})
    if not sol:
        return jsonify({"success": False, "error": "Solution not found"}), 404
        
    upvotes = sol.get("upvotes", [])
    if isinstance(upvotes, int): upvotes = []
    downvotes = sol.get("downvotes", [])
    if isinstance(downvotes, int): downvotes = []
    
    if current_user.id in upvotes: upvotes.remove(current_user.id)
    if current_user.id in downvotes: downvotes.remove(current_user.id)
    
    if action == "up":
        upvotes.append(current_user.id)
    elif action == "down":
        downvotes.append(current_user.id)
        
    db.solutions.update_one(
        {"_id": ObjectId(sol_id)},
        {"$set": {"upvotes": upvotes, "downvotes": downvotes}}
    )
    return jsonify({"success": True, "upvotes": len(upvotes), "downvotes": len(downvotes), "user_vote": action})

@practice_bp.route('/api/solutions/<sol_id>/view', methods=['POST'])
def view_solution(sol_id):
    db.solutions.update_one({"_id": ObjectId(sol_id)}, {"$inc": {"views": 1}})
    return jsonify({"success": True})

@practice_bp.route('/api/code', methods=['GET'])
def get_code():
    if os.path.exists(SOLUTION_FILE):
        with open(SOLUTION_FILE, 'r', encoding='utf-8') as f:
            return jsonify({"code": f.read()})
    return jsonify({"code": ""})

@practice_bp.route('/api/check_auth', methods=['GET'])
def check_auth():
    return jsonify({"authenticated": current_user.is_authenticated})

@practice_bp.route('/api/bookmark/<q_id>', methods=['POST'])
@login_required
def toggle_bookmark(q_id):
    data = request.json
    is_bookmarked = data.get('bookmark', False)
    sheet_slug = data.get('sheet_slug')
    
    progress = load_progress(current_user.id)
    if q_id not in progress:
        progress[q_id] = {}
        
    if sheet_slug:
        if "bookmarked_sheets" not in progress[q_id]:
            existing_slug = progress[q_id].get("sheet_slug")
            if progress[q_id].get("bookmark") and existing_slug:
                progress[q_id]["bookmarked_sheets"] = [existing_slug]
            else:
                progress[q_id]["bookmarked_sheets"] = []
                
        if is_bookmarked:
            if sheet_slug not in progress[q_id]["bookmarked_sheets"]:
                progress[q_id]["bookmarked_sheets"].append(sheet_slug)
        else:
            if sheet_slug in progress[q_id]["bookmarked_sheets"]:
                progress[q_id]["bookmarked_sheets"].remove(sheet_slug)
                
        progress[q_id]["bookmark"] = len(progress[q_id]["bookmarked_sheets"]) > 0
    else:
        progress[q_id]["bookmark"] = is_bookmarked
        
    save_progress(current_user.id, progress)
    
    return jsonify({"success": True})
