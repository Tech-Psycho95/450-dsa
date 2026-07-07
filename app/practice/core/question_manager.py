import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
BANK_DIR = os.path.join(BASE_DIR, "question_bank")
WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")
SOLUTIONS_DIR = os.path.join(BASE_DIR, "solutions")

def get_patterns():
    patterns_file = os.path.join(BANK_DIR, "patterns.json")
    if not os.path.exists(patterns_file):
        return {}
    with open(patterns_file, 'r') as f:
        return json.load(f)

def setup_workspace(category, q_id, include_md=True):
    patterns = get_patterns()
    if category not in patterns or q_id not in patterns[category]:
        return False, "Question not found."

    q_info = patterns[category][q_id]
    file_prefix = q_info["file_prefix"]

    md_path = os.path.join(BANK_DIR, category, f"{file_prefix}.md")
    json_path = os.path.join(BANK_DIR, category, f"{file_prefix}.json")

    if not os.path.exists(md_path) or not os.path.exists(json_path):
        return False, "Error: Question files missing."

    with open(md_path, 'r') as f:
        md_text = f.read()

    with open(json_path, 'r') as f:
        metadata = json.load(f)

    workspace_file = os.path.join(WORKSPACE_DIR, "solution.txt")
    os.makedirs(WORKSPACE_DIR, exist_ok=True)

    with open(workspace_file, 'w') as f:
        if include_md:
            f.write(f"/*\nQuestion: {q_info['name']}\n\n")
            f.write(md_text.strip())
            f.write("\n*/\n\n")
            
        param_names = metadata.get("param_names", ["arg"])
        params_str = ", ".join(["self"] + param_names)
        
        f.write(f"# Required class: {metadata['class_name']}\n")
        f.write(f"# Required method: {metadata['method_name']}({params_str})\n\n")
        f.write(f"class {metadata['class_name']}:\n")
        f.write(f"    def {metadata['method_name']}({params_str}):\n")
        f.write("        pass\n")

    context = {"category": category, "q_id": q_id, "file_prefix": file_prefix}
    with open(os.path.join(WORKSPACE_DIR, "context.json"), 'w') as f:
        json.dump(context, f)

    return True, f"Workspace prepared for '{q_info['name']}'.\nGo edit: {workspace_file}"
