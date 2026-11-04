import logging
import json
import re
from typing import Dict, Any, List, Optional
from utils.gemini import generate_json_response

logger = logging.getLogger(__name__)

# Curated benchmark DSA catalog structured by topics, difficulties, companies, and platforms
DSA_PROBLEMS_CATALOG = [
    # Arrays & Hashing
    {
        "id": "dsa-01",
        "title": "Two Sum",
        "topic": "Arrays & Hashing",
        "difficulty": "Easy",
        "companies": ["Google", "Amazon", "Microsoft", "Meta", "TCS", "Infosys"],
        "description": "Given an array of integers nums and an integer target, return indices of the two numbers such that they add up to target.",
        "skills_targeted": ["Arrays", "Hash Map", "Lookup Optimization", "Python", "Java", "C++"],
        "practice_url": "https://leetcode.com/problems/two-sum/",
        "platform": "LeetCode",
        "time_complexity": "O(N)",
        "space_complexity": "O(N)",
        "hints": ["Use a hash table to store visited numbers and their index.", "Check if target - current_val exists in your map."]
    },
    {
        "id": "dsa-02",
        "title": "Group Anagrams",
        "topic": "Arrays & Hashing",
        "difficulty": "Medium",
        "companies": ["Amazon", "Uber", "Flipkart", "Goldman Sachs"],
        "description": "Given an array of strings strs, group the anagrams together in any order.",
        "skills_targeted": ["Hash Map", "String Manipulation", "Sorting", "Python"],
        "practice_url": "https://leetcode.com/problems/group-anagrams/",
        "platform": "LeetCode",
        "time_complexity": "O(N * K log K)",
        "space_complexity": "O(N * K)",
        "hints": ["Sort each string to use as the canonical dictionary key, or count character frequencies."]
    },
    {
        "id": "dsa-03",
        "title": "Subarray Sum Equals K",
        "topic": "Prefix Sum & Hash Map",
        "difficulty": "Medium",
        "companies": ["Google", "Meta", "Adobe", "Microsoft"],
        "description": "Given an array of integers nums and an integer k, return the total number of subarrays whose sum equals to k.",
        "skills_targeted": ["Prefix Sum", "Hash Map", "Subarrays", "Algorithms"],
        "practice_url": "https://leetcode.com/problems/subarray-sum-equals-k/",
        "platform": "LeetCode",
        "time_complexity": "O(N)",
        "space_complexity": "O(N)",
        "hints": ["Compute prefix sums continuously. Store the frequency of prefix sums encountered in a hash table."]
    },

    # Two Pointers & Sliding Window
    {
        "id": "dsa-04",
        "title": "Longest Substring Without Repeating Characters",
        "topic": "Sliding Window",
        "difficulty": "Medium",
        "companies": ["Amazon", "Google", "Microsoft", "Bloomberg", "Cisco"],
        "description": "Given a string s, find the length of the longest substring without duplicate characters.",
        "skills_targeted": ["Sliding Window", "Two Pointers", "String", "Hash Set"],
        "practice_url": "https://leetcode.com/problems/longest-substring-without-repeating-characters/",
        "platform": "LeetCode",
        "time_complexity": "O(N)",
        "space_complexity": "O(min(N, M))",
        "hints": ["Maintain a window [left, right] and expand right. If duplicate found, shrink window from left."]
    },
    {
        "id": "dsa-05",
        "title": "Trapping Rain Water",
        "topic": "Two Pointers",
        "difficulty": "Hard",
        "companies": ["Google", "Amazon", "Goldman Sachs", "Microsoft"],
        "description": "Given n non-negative integers representing an elevation map where the width of each bar is 1, compute how much water it can trap after raining.",
        "skills_targeted": ["Two Pointers", "Dynamic Programming", "Monotonic Stack"],
        "practice_url": "https://leetcode.com/problems/trapping-rain-water/",
        "platform": "LeetCode",
        "time_complexity": "O(N)",
        "space_complexity": "O(1)",
        "hints": ["Maintain left_max and right_max pointers. Water trapped at any bar depends on min(left_max, right_max)."]
    },

    # Trees & Graphs
    {
        "id": "dsa-06",
        "title": "Lowest Common Ancestor of a Binary Tree",
        "topic": "Binary Trees",
        "difficulty": "Medium",
        "companies": ["Meta", "Amazon", "Microsoft", "LinkedIn"],
        "description": "Given a binary tree, find the lowest common ancestor (LCA) of two given nodes in the tree.",
        "skills_targeted": ["Binary Trees", "Recursion", "DFS", "Tree Traversal"],
        "practice_url": "https://leetcode.com/problems/lowest-common-ancestor-of-a-binary-tree/",
        "platform": "LeetCode",
        "time_complexity": "O(N)",
        "space_complexity": "O(H)",
        "hints": ["Traverse tree recursively. If node matches p or q, bubble it up. If left and right subtrees both return non-null, current node is LCA."]
    },
    {
        "id": "dsa-07",
        "title": "Number of Islands",
        "topic": "Graphs & BFS/DFS",
        "difficulty": "Medium",
        "companies": ["Amazon", "Google", "Bloomberg", "Salesforce", "TCS"],
        "description": "Given an m x n 2D binary grid which represents a map of '1's (land) and '0's (water), return the number of islands.",
        "skills_targeted": ["Graphs", "BFS", "DFS", "Matrix", "Connected Components"],
        "practice_url": "https://leetcode.com/problems/number-of-islands/",
        "platform": "LeetCode",
        "time_complexity": "O(M * N)",
        "space_complexity": "O(M * N)",
        "hints": ["Iterate through every cell. When '1' is encountered, trigger BFS/DFS to sink the island (mark visited) and increment count."]
    },
    {
        "id": "dsa-08",
        "title": "Course Schedule II",
        "topic": "Topological Sort & Graphs",
        "difficulty": "Medium",
        "companies": ["Google", "Amazon", "Uber", "Palantir"],
        "description": "Return the ordering of courses you should finish to complete all courses given their prerequisites. If impossible, return empty array.",
        "skills_targeted": ["Graphs", "Topological Sort", "Kahn's Algorithm", "DAG", "Cycle Detection"],
        "practice_url": "https://leetcode.com/problems/course-schedule-ii/",
        "platform": "LeetCode",
        "time_complexity": "O(V + E)",
        "space_complexity": "O(V + E)",
        "hints": ["Calculate in-degrees for all vertices. Use a queue initialized with in-degree 0 courses."]
    },

    # Dynamic Programming
    {
        "id": "dsa-09",
        "title": "Coin Change",
        "topic": "Dynamic Programming",
        "difficulty": "Medium",
        "companies": ["Amazon", "Apple", "Walmart", "Oracle"],
        "description": "Find the fewest number of coins that you need to make up that amount from given denominations. Return -1 if impossible.",
        "skills_targeted": ["Dynamic Programming", "Knapsack", "Optimization", "Recursion with Memoization"],
        "practice_url": "https://leetcode.com/problems/coin-change/",
        "platform": "LeetCode",
        "time_complexity": "O(Amount * N)",
        "space_complexity": "O(Amount)",
        "hints": ["Define dp[i] as min coins to form amount i. dp[i] = min(dp[i - coin] + 1) for coin in coins."]
    },
    {
        "id": "dsa-10",
        "title": "Longest Increasing Subsequence",
        "topic": "Dynamic Programming",
        "difficulty": "Medium",
        "companies": ["Google", "Microsoft", "Meta", "TCS"],
        "description": "Given an integer array nums, return the length of the longest strictly increasing subsequence.",
        "skills_targeted": ["Dynamic Programming", "Binary Search", "Patience Sorting"],
        "practice_url": "https://leetcode.com/problems/longest-increasing-subsequence/",
        "platform": "LeetCode",
        "time_complexity": "O(N log N)",
        "space_complexity": "O(N)",
        "hints": ["DP approach is O(N^2). Optimize to O(N log N) using tails array with binary search (bisect_left)."]
    },

    # Linked List & Stacks
    {
        "id": "dsa-11",
        "title": "Reverse Linked List",
        "topic": "Linked Lists",
        "difficulty": "Easy",
        "companies": ["Amazon", "Microsoft", "Apple", "Infosys", "Capgemini"],
        "description": "Given the head of a singly linked list, reverse the list, and return the reversed list.",
        "skills_targeted": ["Linked Lists", "Pointers", "Recursion", "Iterative"],
        "practice_url": "https://leetcode.com/problems/reverse-linked-list/",
        "platform": "LeetCode",
        "time_complexity": "O(N)",
        "space_complexity": "O(1)",
        "hints": ["Keep three pointers: prev, curr, next_node. Reassign curr.next = prev."]
    },
    {
        "id": "dsa-12",
        "title": "Valid Parentheses",
        "topic": "Stacks",
        "difficulty": "Easy",
        "companies": ["Google", "Amazon", "Meta", "Accenture", "Wipro"],
        "description": "Given a string s containing just the characters '(', ')', '{', '}', '[' and ']', determine if the input string is valid.",
        "skills_targeted": ["Stacks", "String", "Parsing"],
        "practice_url": "https://leetcode.com/problems/valid-parentheses/",
        "platform": "LeetCode",
        "time_complexity": "O(N)",
        "space_complexity": "O(N)",
        "hints": ["Use a stack. Push opening brackets; pop and verify match when closing brackets appear."]
    }
]

class CodingPracticeAgent:
    """
    Personalised Coding Practice Recommendation Agent (#147).
    Identifies student skill gaps and targets, matches benchmark interview DSA problems,
    and constructs weekly structured study roadmaps.
    """

    def __init__(self):
        self.catalog = DSA_PROBLEMS_CATALOG

    def recommend_problems(
        self,
        skill_gaps: Optional[List[str]] = None,
        target_company: Optional[str] = None,
        difficulty_preference: Optional[str] = None,
        limit: int = 6
    ) -> Dict[str, Any]:
        """
        Recommends tailored coding challenges matching candidate skill weaknesses and dream companies.
        """
        skill_gaps = skill_gaps or []
        target_company = (target_company or "").strip()
        difficulty_preference = (difficulty_preference or "All").strip()

        # Score problems against student profile
        scored_problems = []
        for prob in self.catalog:
            relevance_score = 10  # base score
            match_reasons = []

            # 1. Company match
            if target_company:
                comp_matches = [
                    c for c in prob["companies"]
                    if target_company.lower() in c.lower() or c.lower() in target_company.lower()
                ]
                if comp_matches:
                    relevance_score += 35
                    match_reasons.append(f"Frequently asked in {comp_matches[0]} interviews")

            # 2. Skill gap match
            prob_skills = [s.lower() for s in prob["skills_targeted"]]
            for gap in skill_gaps:
                gap_clean = gap.strip().lower()
                if not gap_clean:
                    continue
                for ps in prob_skills:
                    if gap_clean in ps or ps in gap_clean:
                        relevance_score += 25
                        match_reasons.append(f"Targets identified gap: '{gap.strip()}'")
                        break

            # 3. Difficulty preference weighting
            if difficulty_preference and difficulty_preference.lower() not in ("all", "any"):
                if prob["difficulty"].lower() == difficulty_preference.lower():
                    relevance_score += 20
                else:
                    relevance_score -= 15

            if not match_reasons:
                match_reasons.append(f"Core {prob['topic']} foundation problem")

            scored_problems.append({
                "problem": prob,
                "relevance_score": relevance_score,
                "match_reasons": list(dict.fromkeys(match_reasons))  # dedup
            })

        # Sort descending by relevance score
        scored_problems.sort(key=lambda x: x["relevance_score"], reverse=True)
        top_recommendations = scored_problems[:limit]

        # Structure response payload
        results = [
            {
                **item["problem"],
                "relevance_score": item["relevance_score"],
                "match_reasons": item["match_reasons"]
            }
            for item in top_recommendations
        ]

        study_plan = self._generate_study_roadmap(results, target_company)

        return {
            "target_company": target_company or "General Tech Placements",
            "skill_gaps_addressed": skill_gaps,
            "total_recommended": len(results),
            "recommendations": results,
            "study_plan": study_plan
        }

    def _generate_study_roadmap(self, recommendations: List[Dict[str, Any]], company: str) -> List[Dict[str, Any]]:
        """
        Organizes recommended problems into a practical weekly preparation roadmap.
        """
        plan = [
            {
                "phase": "Day 1-2: Core Foundations & Data Structures",
                "focus": "Hash Maps, Two Pointers & Basic Traversals",
                "problems": [r["title"] for r in recommendations if r["difficulty"] in ("Easy", "Medium")][:3]
            },
            {
                "phase": "Day 3-5: Deep Algorithms & Optimization",
                "focus": "Sliding Window, Trees, Graphs & Dynamic Programming",
                "problems": [r["title"] for r in recommendations if r["difficulty"] in ("Medium", "Hard")][:3]
            },
            {
                "phase": "Day 6-7: Timed Mock Code Execution",
                "focus": f"Simulate real-time 45min technical interview rounds for {company or 'target company'}",
                "problems": [r["title"] for r in recommendations][-2:] if len(recommendations) >= 2 else ["Full Review"]
            }
        ]
        return plan
