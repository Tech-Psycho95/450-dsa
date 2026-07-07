import sys
from app.practice.core.question_manager import get_patterns, setup_workspace
from app.practice.core.tester import test_solution

def print_menu():
    print("\n" + "="*30)
    print("   Hard-Mode DSA Platform   ")
    print("="*30)
    print("1. browse - Select a category and question")
    print("2. run    - Compile and test against mock batch")
    print("3. submit - Compile and test against all cases")
    print("4. exit   - Leave the platform")
    print("="*30 + "\n")

def handle_browse():
    patterns = get_patterns()
    if not patterns:
        print("No patterns found in question bank.")
        return

    print("Categories:")
    categories = list(patterns.keys())
    for i, cat in enumerate(categories):
        print(f"{i+1}. {cat}")
    
    try:
        cat_idx = int(input("\nSelect category number: ")) - 1
        if cat_idx < 0 or cat_idx >= len(categories):
            print("Invalid category.")
            return
        category = categories[cat_idx]

        print(f"\nQuestions in '{category}':")
        q_ids = list(patterns[category].keys())
        for q_id in q_ids:
            print(f"[{q_id}] {patterns[category][q_id]['name']}")
        
        q_id = input("\nSelect question ID: ").strip()
        if q_id not in q_ids:
            print("Invalid question ID.")
            return
        
        success, msg = setup_workspace(category, q_id)
        print("\n" + msg)
    except ValueError:
        print("Invalid input.")

def handle_run():
    print("Running code against mock test cases...")
    success, msg = test_solution(mode="run")
    print("\n" + msg)

def handle_submit():
    print("Submitting code against all test cases...")
    success, msg = test_solution(mode="submit")
    print("\n" + msg)

def main_loop():
    while True:
        print_menu()
        choice = input("Enter command (browse/run/submit/exit): ").strip().lower()
        if choice in ['1', 'browse']:
            handle_browse()
        elif choice in ['2', 'run']:
            handle_run()
        elif choice in ['3', 'submit']:
            handle_submit()
        elif choice in ['4', 'exit', 'quit']:
            print("Exiting...")
            sys.exit(0)
        else:
            print("Unknown command. Try again.")
