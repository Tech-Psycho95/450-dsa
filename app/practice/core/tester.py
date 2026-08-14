import os
import json
import shutil
from app.practice.core.executor import run_code
from app.practice.core.question_manager import get_patterns, BANK_DIR, SOLUTIONS_DIR, WORKSPACE_DIR

def test_solution(mode="run", custom_cases=None):
    context_file = os.path.join(WORKSPACE_DIR, "context.json")
    if not os.path.exists(context_file):
        return False, "No active question. Use 'browse' to select one first."

    with open(context_file, 'r') as f:
        context = json.load(f)

    category = context["category"]
    file_prefix = context["file_prefix"]
    q_id = context["q_id"]

    json_path = os.path.join(BANK_DIR, category, f"{file_prefix}.json")
    if not os.path.exists(json_path):
        return False, f"Error: Metadata file missing at {json_path}"

    with open(json_path, 'r') as f:
        metadata = json.load(f)

    if custom_cases is not None:
        test_cases = custom_cases
    else:
        test_cases = metadata.get("test_cases", [])
        if mode == "run":
            test_cases = test_cases[:2]  # Mock batch

    success, payload = run_code(test_cases, metadata)
    
    if not success:
        return False, {
            "status": "Runtime Error", 
            "error_msg": payload, 
            "passed": 0, 
            "total": len(test_cases)
        }

    results = payload["results"]
    user_stdout = payload["stdout"]
    user_stderr = payload["stderr"]

    if isinstance(results, dict) and "error" in results:
        return False, {
            "status": "Setup Error",
            "error_msg": results['error'],
            "passed": 0,
            "total": len(test_cases)
        }

    passed_count = 0
    first_failed_test = None
    
    for i, res in enumerate(results):
        if res.get("pass"):
            passed_count += 1
        else:
            if first_failed_test is None:
                first_failed_test = res
                first_failed_test["index"] = i + 1

    total = len(test_cases)
    
    response_data = {
        "passed": passed_count,
        "total": total,
        "stdout": user_stdout,
        "stderr": user_stderr
    }

    if passed_count == total:
        response_data["status"] = "Accepted"
        if mode == "submit":
            patterns = get_patterns()
            q_name = patterns[category][q_id]["name"].replace(" ", "_").lower()
            cat_sol_dir = os.path.join(SOLUTIONS_DIR, category)
            os.makedirs(cat_sol_dir, exist_ok=True)
            
            sol_file = os.path.join(cat_sol_dir, f"{q_name}.py")
            shutil.copy(os.path.join(WORKSPACE_DIR, "solution.txt"), sol_file)
            response_data["saved_to"] = sol_file
            
            # Clear workspace completely
            with open(os.path.join(WORKSPACE_DIR, "solution.txt"), 'w') as f:
                f.write("# Workspace cleared. Use 'browse' to load another question.\n")
            os.remove(context_file)

        return True, response_data
    else:
        response_data["status"] = "Wrong Answer" if "error" not in first_failed_test else "Runtime Error"
        response_data["failed_test"] = first_failed_test
        return False, response_data
