import json

import problem_scraper_app as scraper


LEETCODE_PAYLOAD = {
    "data": {
        "question": {
            "title": "Two Sum",
            "titleSlug": "two-sum",
            "content": """
                <p>Given an array of integers nums and an integer target, return the two indices.</p>
                <p><strong>Example 1:</strong></p>
                <p><strong>Input:</strong> nums = [2,7,11,15], target = 9<br>
                <strong>Output:</strong> [0,1]<br>
                <strong>Explanation:</strong> nums[0] + nums[1] = 9.</p>
                <p><strong>Constraints:</strong></p><ul><li>2 &lt;= nums.length &lt;= 10^4</li></ul>
            """,
            "difficulty": "Easy",
            "exampleTestcases": "[2,7,11,15]\\n9",
            "topicTags": [{"name": "Array"}, {"name": "Hash Table"}],
            "codeSnippets": [
                {"lang": "Python3", "langSlug": "python3", "code": "class Solution:\\n    def twoSum(self, nums, target):\\n        pass"}
            ],
            "similarQuestions": json.dumps(
                [{"title": "3Sum", "difficulty": "MEDIUM", "titleSlug": "3sum"}]
            ),
            "stats": json.dumps(
                {"totalAcceptedRaw": 10, "totalSubmissionRaw": 20, "acRate": "50.0%"}
            ),
            "likes": 5,
            "dislikes": 1,
        }
    }
}

GFG_HTML = """
<html><head><title>Array Reverse - GeeksforGeeks</title></head><body>
<main><h1>Array Reverse</h1>
<p>Reverse the elements of the given array.</p>
<p><strong>Examples:</strong></p>
<p><strong>Input:</strong> arr[] = [1, 2, 3]<br>
<strong>Output:</strong> [3, 2, 1]<br>
<strong>Explanation:</strong> The order is reversed.</p>
<p>Difficulty: Easy</p>
<p>Expected Time Complexity: O(n)</p>
<p>Auxiliary Space: O(1)</p>
<a href="/tag/amazon/">Amazon</a><a href="/category/dsa/data-structures/c-arrays/">Arrays</a>
</main></body></html>
"""

GFG_PRACTICE_DATA = {
    "props": {
        "problem": {
            "problem_name": "Kth Smallest",
            "slug": "kth-smallest-element5635",
            "problem_question": """
                <p>Given an integer array <strong>arr[]</strong> and integer k, return the kth smallest.</p>
                <pre><strong>Input:</strong> arr[] = [7, 10, 4, 3, 20, 15], k = 3
                <strong>Output:</strong> 7
                <strong>Explanation:</strong> The third smallest value is 7.</pre>
                <p><strong>Constraints:</strong><br>1 &lt;= arr.size() &lt;= 10<sup>5</sup><br>1 &lt;= k &lt;= arr.size()</p>
            """,
            "difficulty": "Medium",
            "marks": 4,
            "all_submissions": 1000,
            "accuracy": "35.5%",
            "tags": {
                "company_tags": ["Amazon", "Microsoft", "Google"],
                "topic_tags": ["Arrays", "Searching", "Sorting"],
            },
            "extra": {
                "initial_user_func": {
                    "python3": {
                        "user_code": "class Solution:\n    def kthSmallest(self, arr, k):\n        pass"
                    }
                }
            },
        }
    }
}


class FakeResponse:
    def __init__(self, *, json_value=None, text_value=""):
        self._json = json_value
        self.text = text_value

    def json(self):
        return self._json

    def raise_for_status(self):
        return None


def test_detect_platform():
    assert scraper.detect_platform("https://leetcode.com/problems/two-sum/") == "leetcode"
    assert scraper.detect_platform("https://www.geeksforgeeks.org/problems/two-sum/1") == "gfg"


def test_leetcode_scrape(monkeypatch):
    monkeypatch.setattr(
        scraper.requests, "post", lambda *args, **kwargs: FakeResponse(json_value=LEETCODE_PAYLOAD)
    )
    item = scraper.scrape_problem("https://leetcode.com/problems/two-sum/")
    assert item["titleSlug"] == "two-sum"
    assert item["difficulty"] == "Easy"
    assert item["starterCode"].startswith("class Solution")
    assert item["stats"]["acceptanceRate"] == 50.0
    assert "expectedComplexity" in item
    assert "Example 1" not in item["content"]
    assert "Constraints" not in item["content"]


def test_gfg_scrape(monkeypatch):
    monkeypatch.setattr(
        scraper.requests, "get", lambda *args, **kwargs: FakeResponse(text_value=GFG_HTML)
    )
    item = scraper.scrape_problem("https://www.geeksforgeeks.org/write-a-program-to-reverse-an-array/")
    assert item["title"] == "Array Reverse"
    assert item["difficulty"] == "Easy"
    assert item["expectedComplexity"] == {"time": "O(n)", "space": "O(1)"}
    assert item["companies"] == ["Amazon"]


def test_gfg_practice_scrape(monkeypatch):
    page = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(GFG_PRACTICE_DATA)}</script>'

    def fake_get(url, *args, **kwargs):
        if "metainfo" in url:
            return FakeResponse(
                json_value={
                    "results": {
                        "expected_time_complexity": "O(n log k)",
                        "expected_auxiliary_space": "O(k)",
                    }
                }
            )
        return FakeResponse(text_value=page)

    monkeypatch.setattr(scraper.requests, "get", fake_get)
    item = scraper.scrape_problem(
        "https://www.geeksforgeeks.org/problems/kth-smallest-element5635/1"
    )
    assert item["title"] == "Kth Smallest"
    assert item["difficulty"] == "Medium"
    assert item["topics"] == ["Arrays", "Searching", "Sorting"]
    assert item["companies"] == ["Amazon", "Microsoft", "Google"]
    assert item["constraints"] == ["1 <= arr.size() <= 10^5", "1 <= k <= arr.size()"]
    assert item["starterCode"].startswith("class Solution")
    assert item["stats"]["totalAccepted"] == 355
    assert item["expectedComplexity"] == {"time": "O(n log k)", "space": "O(k)"}
    assert "Input:" not in item["content"]
    assert "Constraints" not in item["content"]


def test_web_ui_and_validation():
    client = scraper.app.test_client()
    assert client.get("/").status_code == 200
    response = client.post(
        "/api/scrape", json={"url": "https://example.com/problem", "sheet": "Test Sheet"}
    )
    assert response.status_code == 400
    assert "Only LeetCode" in response.get_json()["error"]


def test_bulk_scrape_returns_one_problem_array_and_individual_errors(monkeypatch):
    monkeypatch.setattr(
        scraper.requests, "post", lambda *args, **kwargs: FakeResponse(json_value=LEETCODE_PAYLOAD)
    )
    response = scraper.app.test_client().post(
        "/api/scrape",
        json={
            "urls": "https://leetcode.com/problems/two-sum/\n"
            "https://example.com/not-supported",
            "sheet": "Love Babbar DSA",
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert [item["titleSlug"] for item in payload["problems"]] == ["two-sum"]
    assert payload["problems"][0]["sheetName"] == "Love Babbar DSA"
    assert payload["problems"][0]["sheetIds"] == ["love-babbar-dsa"]
    assert len(payload["errors"]) == 1


def test_parse_url_input_accepts_json_array_and_object():
    expected = [
        "https://leetcode.com/problems/two-sum/",
        "https://leetcode.com/problems/valid-parentheses/",
    ]
    assert scraper.parse_url_input(json.dumps(expected)) == expected
    assert scraper.parse_url_input(json.dumps({"urls": expected})) == expected


def test_bulk_save_writes_all_records_once(monkeypatch, tmp_path):
    output = tmp_path / "all-problems.json"
    monkeypatch.setattr(scraper, "OUTPUT_FILE", output)
    first = scraper.blank_record()
    first.update({"titleSlug": "one", "title": "One"})
    second = scraper.blank_record()
    second.update({"titleSlug": "two", "title": "Two"})

    response = scraper.app.test_client().post(
        "/api/save", json={"problems": [first, second]}
    )

    assert response.status_code == 200
    assert response.get_json()["saved"] == 2
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert [item["questionId"] for item in saved] == [1, 2]
    assert [item["titleSlug"] for item in saved] == ["one", "two"]
