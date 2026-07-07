import os
import json
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")

def run_code(test_cases, metadata, user_code, timeout=3):
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    temp_runner = os.path.join(WORKSPACE_DIR, ".temp_runner.py")
    result_file = os.path.join(WORKSPACE_DIR, ".result.json")

    if not user_code.strip():
        return False, "Error: Code is empty."

    # Build the hidden runner script
    runner_code = user_code + "\n\n"
    runner_code += "import sys\n"
    runner_code += "import json\n"
    runner_code += "import traceback\n"
    runner_code += "import time\n"
    runner_code += "import tracemalloc\n\n"
    runner_code += "def __run_tests():\n"
    runner_code += "    tracemalloc.start()\n"
    runner_code += "    start_time = time.perf_counter()\n"
    # Using json.loads to safely parse boolean and null payloads without python SyntaxErrors
    runner_code += f"    test_cases = json.loads(r'''{json.dumps(test_cases)}''')\n"
    runner_code += f"    result_file = r'''{result_file}'''\n"
    runner_code += "    results = []\n"
    runner_code += "    try:\n"
    runner_code += f"        sol = {metadata['class_name']}()\n"
    runner_code += "    except Exception as e:\n"
    runner_code += "        with open(result_file, 'w') as f:\n"
    runner_code += f"            json.dump({{'results': [{{'pass': False, 'error': f'Failed to initialize {metadata['class_name']}: {{str(e)}}'}}], 'runtime_ms': 0, 'memory_mb': 0}}, f)\n"
    runner_code += "        sys.exit(0)\n\n"
    runner_code += "    for tc in test_cases:\n"
    runner_code += "        try:\n"
    runner_code += "            inp = tc['input']\n"
    runner_code += "            import re, ast\n"
    runner_code += "            if isinstance(inp, str) and '=' in inp:\n"
    runner_code += "                parts = re.split(r'(?:^|,\\s*)([a-zA-Z_]\\w*)\\s*=', inp)\n"
    runner_code += "                args = []\n"
    runner_code += "                for i in range(1, len(parts), 2):\n"
    runner_code += "                    val_str = parts[i+1].strip()\n"
    runner_code += "                    try:\n"
    runner_code += "                        args.append(ast.literal_eval(val_str))\n"
    runner_code += "                    except:\n"
    runner_code += "                        args.append(val_str)\n"
    runner_code += f"                res = sol.{metadata['method_name']}(*args)\n"
    runner_code += "            elif isinstance(inp, list):\n"
    runner_code += f"                res = sol.{metadata['method_name']}(*inp)\n"
    runner_code += "            else:\n"
    runner_code += f"                res = sol.{metadata['method_name']}(inp)\n"
    runner_code += "            \n"
    runner_code += "            # evaluate expected to python object if it's a string\n"
    runner_code += "            expected_val = tc.get('expected', tc.get('output'))\n"
    runner_code += "            if isinstance(expected_val, str):\n"
    runner_code += "                try: expected_val = ast.literal_eval(expected_val)\n"
    runner_code += "                except: pass\n"
    runner_code += "            results.append({'pass': res == expected_val, 'actual': res, 'expected': expected_val, 'input': tc['input']})\n"
    runner_code += "        except Exception as e:\n"
    runner_code += "            expected_val = tc.get('expected', tc.get('output'))\n"
    runner_code += "            results.append({'pass': False, 'error': f'{type(e).__name__}: {str(e)}', 'expected': expected_val})\n"
    runner_code += "            break\n\n"
    runner_code += "    end_time = time.perf_counter()\n"
    runner_code += "    current_mem, peak_mem = tracemalloc.get_traced_memory()\n"
    runner_code += "    tracemalloc.stop()\n"
    runner_code += "    total_time_ms = (end_time - start_time) * 1000\n"
    runner_code += "    peak_mem_mb = peak_mem / (1024 * 1024)\n"
    runner_code += "    with open(result_file, 'w') as f:\n"
    runner_code += "        json.dump({'results': results, 'runtime_ms': total_time_ms, 'memory_mb': peak_mem_mb}, f)\n\n"
    runner_code += "if __name__ == '__main__':\n"
    runner_code += "    __run_tests()\n"

    with open(temp_runner, 'w') as f:
        f.write(runner_code)

    try:
        if os.path.exists(result_file):
            os.remove(result_file)

        result = subprocess.run(
            ["python", temp_runner],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        # If execution fails at the syntax level or imports
        if result.returncode != 0 and not os.path.exists(result_file):
            err_out = result.stderr.strip()
            # Try to parse the python syntax error cleanly
            lines = err_out.split('\n')
            clean_err = err_out
            for i, line in enumerate(lines):
                if line.strip().startswith('File "') and 'line ' in line:
                    try:
                        line_part = line.split('line ')[1].split(',')[0].strip()
                        err_msg = lines[-1]
                        clean_err = f"{err_msg}\nLine {line_part} (solution.txt)"
                        break
                    except:
                        pass
            return False, f"{clean_err}"
        
        if not os.path.exists(result_file):
            return False, f"Unknown Error: Test runner failed to produce results.\nOutput: {result.stdout}\nError: {result.stderr}"

        with open(result_file, 'r') as f:
            output_data = json.load(f)

        return True, {
            "results": output_data.get("results", []),
            "runtime_ms": output_data.get("runtime_ms", 0),
            "memory_mb": output_data.get("memory_mb", 0),
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip()
        }
        
    except subprocess.TimeoutExpired:
        return False, f"Timeout Error: Code execution exceeded the {timeout}s time limit (Possible Infinite Loop)."
    except Exception as e:
        return False, f"System Error: {str(e)}"
    finally:
        # Cleanup
        if os.path.exists(temp_runner):
            os.remove(temp_runner)
        if os.path.exists(result_file):
            os.remove(result_file)
