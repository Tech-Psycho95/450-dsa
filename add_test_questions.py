import os
from pymongo import MongoClient
from datetime import datetime, timezone

db = MongoClient('mongodb://localhost:27017/').get_database('450_dsa')
db.question.update_many({}, {"$set": {"sheetIds": ["love-babbar-dsa"]}})

# Insert one test question for Love Babbar
db.question.insert_one({
    "questionId": 9991,
    "titleSlug": "love-babbar-test-question",
    "title": "Love Babbar Test Question",
    "content": "<p>This is a test question explicitly for the Love Babbar Sheet.</p>",
    "difficulty": "Easy",
    "topics": ["Array"],
    "companies": ["TestCorp"],
    "examples": [{"input": "test", "output": "test", "explanation": "test"}],
    "constraints": ["1 <= N <= 10"],
    "expectedComplexity": {"time": "O(1)", "space": "O(1)"},
    "similarQuestions": [],
    "stats": {"totalAccepted": 0, "totalSubmissions": 0, "acceptanceRate": 0.0, "likes": 0, "dislikes": 0},
    "status": "published",
    "createdAt": datetime.now(timezone.utc),
    "updatedAt": datetime.now(timezone.utc),
    "sheetIds": ["love-babbar-dsa"]
})

# Insert one test question for Striver
db.question.insert_one({
    "questionId": 9992,
    "titleSlug": "striver-test-question",
    "title": "Striver Test Question",
    "content": "<p>This is a test question explicitly for the Striver SDE Sheet.</p>",
    "difficulty": "Hard",
    "topics": ["Dynamic Programming"],
    "companies": ["StriverCorp"],
    "examples": [{"input": "test", "output": "test", "explanation": "test"}],
    "constraints": ["1 <= N <= 10"],
    "expectedComplexity": {"time": "O(N)", "space": "O(N)"},
    "similarQuestions": [],
    "stats": {"totalAccepted": 0, "totalSubmissions": 0, "acceptanceRate": 0.0, "likes": 0, "dislikes": 0},
    "status": "published",
    "createdAt": datetime.now(timezone.utc),
    "updatedAt": datetime.now(timezone.utc),
    "sheetIds": ["striver-sde-sheet"]
})

print("Added test questions!")