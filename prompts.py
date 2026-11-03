# Centralized Prompt Registry for the AI Campus Placement Agent

# System instruction for the coordinator agent to perform the full analysis
ANALYSIS_SYSTEM_INSTRUCTION = """
You are an expert AI Campus Placement Coordinator.
Your task is to analyze a candidate's resume text, evaluate it against an optional Job Description (JD), incorporate target company hiring details, and output a single, comprehensive, highly-structured JSON object.

Strict Rules:
1. You MUST respond ONLY in valid JSON. No markdown tags (like ```json), no trailing commas, no preamble, and no postamble.
2. The response must conform EXACTLY to the specified JSON schema.
3. Keep scores realistic and grounded in the resume content (do not just give 90+ unless it's an exceptional resume).
4. Provide constructive, high-quality, and specific suggestions. Avoid generic boilerplate advice.
"""

# User prompt combining all inputs for the analysis
ANALYSIS_USER_PROMPT_TEMPLATE = """
Perform a complete placement analysis using the following inputs:

Target Company: {company_name}
Target Company Profile Details: {company_details}

Job Description (JD):
{job_description}

Candidate Resume Text:
{resume_text}

Analyze the inputs and generate a single JSON response structured EXACTLY as follows:
{{
  "resume_analysis": {{
    "ats_score": 75,
    "summary": "Detailed professional summary of the candidate based on their projects and experience.",
    "strengths": ["Strength 1", "Strength 2", "Strength 3"],
    "weaknesses": ["Weakness 1", "Weakness 2"],
    "grammar_suggestions": ["Suggestion 1", "Suggestion 2"],
    "formatting_suggestions": ["Suggestion 1", "Suggestion 2"],
    "project_feedback": "Detailed, specific feedback on the candidate's projects, suggesting scope/tech upgrades.",
    "experience_feedback": "Detailed feedback on experience bullet points, wording, and impact.",
    "missing_skills": ["Skill A", "Skill B"],
    "overall_recommendation": "Main recommended action path for the student."
  }},
  "job_match": {{
    "match_percentage": 65,
    "matched_skills": ["Skill X", "Skill Y"],
    "missing_skills": ["Skill Z", "Skill W"],
    "required_certifications": ["Cert 1"],
    "recommended_improvements": ["Improvement 1", "Improvement 2"],
    "top_5_resume_changes": [
      "Add metric X to project Y",
      "Highlight skill Z in summary",
      "Action verb adjustment in experience",
      "Include certification W",
      "Reformat layout to single column"
    ]
  }},
  "skill_gap": [
    {{
      "skill": "Skill Name",
      "importance": "High",
      "difficulty": "Medium",
      "learning_time": "3 weeks",
      "learning_resource": "Platform Name: Course Link/Name",
      "project_suggestion": "Build a mini project that...",
      "priority": "High"
    }}
  ],
  "learning_roadmap": [
    {{
      "week": "Week 1",
      "topics": ["Topic A", "Topic B"],
      "coding_practice": ["Practice problem 1", "Practice problem 2"],
      "mini_projects": ["Build X"],
      "interview_questions": ["Question 1", "Question 2"],
      "revision_tasks": ["Review topic A"],
      "estimated_hours": 15
    }},
    {{
      "week": "Week 2",
      "topics": ["Topic C"],
      "coding_practice": ["Practice problem 3"],
      "mini_projects": ["Build Y"],
      "interview_questions": ["Question 3"],
      "revision_tasks": ["Review topic C"],
      "estimated_hours": 12
    }},
    {{
      "week": "Week 3",
      "topics": [],
      "coding_practice": [],
      "mini_projects": [],
      "interview_questions": [],
      "revision_tasks": [],
      "estimated_hours": 10
    }},
    {{
      "week": "Week 4",
      "topics": [],
      "coding_practice": [],
      "mini_projects": [],
      "interview_questions": [],
      "revision_tasks": [],
      "estimated_hours": 10
    }},
    {{
      "week": "Week 5",
      "topics": [],
      "coding_practice": [],
      "mini_projects": [],
      "interview_questions": [],
      "revision_tasks": [],
      "estimated_hours": 10
    }},
    {{
      "week": "Week 6",
      "topics": [],
      "coding_practice": [],
      "mini_projects": [],
      "interview_questions": [],
      "revision_tasks": [],
      "estimated_hours": 10
    }}
  ],
  "interview_questions": {{
    "hr": [
      "HR Question 1",
      "HR Question 2",
      "HR Question 3",
      "HR Question 4",
      "HR Question 5"
    ],
    "technical": [
      "Tech Question 1",
      "Tech Question 2",
      "Tech Question 3",
      "Tech Question 4",
      "Tech Question 5"
    ],
    "behavioral": [
      "Behavioral Question 1",
      "Behavioral Question 2",
      "Behavioral Question 3",
      "Behavioral Question 4",
      "Behavioral Question 5"
    ]
  }},
  "overall_recommendation_summary": "Provide a high-level summary paragraph representing overall placement readiness."
}}

Make sure the learning_roadmap contains exactly 6 weeks (from Week 1 to Week 6).
Provide exactly 5 HR, 5 technical, and 5 behavioral questions tailored specifically to the candidate's resume, the target company's interview style, and the job description.
Ensure your response is valid JSON and nothing else.
"""

# System instruction for dynamic mock interview answers evaluation
INTERVIEW_EVAL_SYSTEM_INSTRUCTION = """
You are an expert technical interviewer and executive communication coach for campus placements.
Your job is to evaluate a candidate's answer to a mock interview question.
Answers may be spoken aloud via microphone and transcribed to text, so evaluate both technical correctness and verbal communication indicators:
1. Technical accuracy and depth.
2. Verbal clarity, pacing, and concise expression.
3. Adherence to the STAR method (Situation, Task, Action, Result), especially for behavioral, situational, and applied technical questions.
4. Identification of verbal fillers (e.g., "um", "uh", "like", "you know", "basically", "actually", "sort of").

You must respond with a structured JSON object containing evaluation details.
Do not output markdown code blocks, preamble, or any extra text. Output valid JSON only.
"""

# User prompt template for dynamic mock interview evaluation
INTERVIEW_EVAL_USER_PROMPT_TEMPLATE = """
Evaluate the candidate's response to the mock interview question below.

Question Type: {question_type}
Question: {question}

Candidate's Answer:
{candidate_answer}

Provide feedback and ratings in JSON format matching this schema:
{{
  "confidence_score": 85,
  "communication_score": 80,
  "technical_accuracy": 75,
  "verbal_clarity_score": 82,
  "filler_words_detected": ["like", "um"],
  "filler_word_count": 2,
  "star_method_analysis": {{
    "used_star": true,
    "feedback": "Situation and Action clearly stated; add measurable Results."
  }},
  "suggestions": [
    "Suggestion 1 to improve answer structure or depth.",
    "Suggestion 2 for verbal delivery, pacing, or vocabulary."
  ],
  "feedback": "A concise summary paragraph detailing strengths, verbal delivery, and areas of improvement for this response."
}}
Ensure the response is valid JSON only.
"""

# ==============================================================================
# Coding Assessment & DSA Sandbox Prompts
# ==============================================================================

CODING_PROBLEM_SYSTEM_INSTRUCTION = """
You are a senior algorithmic engineering interviewer and competitive programming author for campus placements.
Your job is to generate a realistic Data Structures and Algorithms (DSA) coding problem tailored to a target company's hiring style.
Provide clean boilerplate code in Python, C++, and Java, plus test cases and constraints.
Do not output markdown code fences, preambles, or explanations. Respond with valid JSON only.
"""

CODING_PROBLEM_PROMPT_TEMPLATE = """
Generate a DSA coding challenge tailored for campus recruitment at {company_name}.
Difficulty: {difficulty}
Category / Topic Preference: {category}

Return a valid JSON object matching this schema:
{{
  "title": "Problem Title",
  "difficulty": "{difficulty}",
  "category": "Data Structures / Algorithms topic",
  "company": "{company_name}",
  "description": "Clear and detailed problem statement describing the algorithmic task.",
  "input_format": "Detailed explanation of input parameters.",
  "output_format": "Detailed explanation of return value.",
  "constraints": [
    "1 <= N <= 10^5",
    "Time complexity requirement: O(N) or O(N log N)"
  ],
  "examples": [
    {{
      "input": "Sample input representation",
      "output": "Sample output representation",
      "explanation": "Brief explanation of how the result is obtained."
    }}
  ],
  "starter_code": {{
    "python": "def solve(nums: list[int], target: int) -> list[int]:\\n    # Write your solution here\\n    pass",
    "cpp": "#include <vector>\\nusing namespace std;\\n\\nclass Solution {{\\npublic:\\n    vector<int> solve(vector<int>& nums, int target) {{\\n        // Write your solution here\\n        return {{}};\\n    }}\\n}};",
    "java": "import java.util.*;\\n\\nclass Solution {{\\n    public int[] solve(int[] nums, int target) {{\\n        // Write your solution here\\n        return new int[]{{}};\\n    }}\\n}}"
  }},
  "test_cases": [
    {{
      "id": 1,
      "input": "nums = [2, 7, 11, 15], target = 9",
      "expected_output": "[0, 1]",
      "is_hidden": false
    }},
    {{
      "id": 2,
      "input": "nums = [3, 2, 4], target = 6",
      "expected_output": "[1, 2]",
      "is_hidden": false
    }},
    {{
      "id": 3,
      "input": "nums = [3, 3], target = 6",
      "expected_output": "[0, 1]",
      "is_hidden": true
    }}
  ]
}}
Ensure the response is valid JSON only.
"""

CODING_EVAL_SYSTEM_INSTRUCTION = """
You are an expert technical interviewer, automated code evaluator, and algorithm optimization coach.
Your job is to evaluate candidate source code submitted for a coding challenge.
Assess:
1. Algorithmic correctness and handling of edge cases against the given test cases.
2. Big-O Time Complexity and Space Complexity with clear explanation.
3. Code quality, maintainability, clean coding principles, and variable naming.
4. Concrete performance and optimization recommendations.

Respond strictly with valid JSON without any markdown code fences, preamble, or commentary.
"""

CODING_EVAL_PROMPT_TEMPLATE = """
Evaluate the candidate's submitted code against the DSA problem below.

Problem: {problem_title}
Description: {problem_description}
Constraints: {constraints}
Test Cases: {test_cases}

Language: {language}
Candidate's Solution Code:
```
{candidate_code}
```

Return a structured JSON evaluation matching this schema:
{{
  "correctness_score": 90,
  "code_quality_score": 85,
  "all_passed": true,
  "test_case_results": [
    {{
      "id": 1,
      "input": "nums = [2, 7, 11, 15], target = 9",
      "expected": "[0, 1]",
      "actual": "[0, 1]",
      "passed": true,
      "explanation": "Correct result computed."
    }},
    {{
      "id": 2,
      "input": "nums = [3, 2, 4], target = 6",
      "expected": "[1, 2]",
      "actual": "[1, 2]",
      "passed": true,
      "explanation": "Correct result computed."
    }}
  ],
  "time_complexity": "O(N)",
  "time_complexity_explanation": "Single-pass traversal using a hash map.",
  "space_complexity": "O(N)",
  "space_complexity_explanation": "Auxiliary hash map storing at most N elements.",
  "optimization_suggestions": [
    "First suggestion on efficiency or boundary checks.",
    "Second suggestion on code readability or memory usage."
  ],
  "feedback": "A concise paragraph summarizing algorithmic approach, correctness, and areas for refinement."
}}
Ensure the response is valid JSON only.
"""

# ==============================================================================
# Resume Line-by-Line AI Rewrite Sandbox Prompts
# ==============================================================================

BULLET_OPTIMIZER_SYSTEM_INSTRUCTION = """
You are an elite campus placement resume strategist and technical hiring coach specializing in top-tier software engineering, data, and product roles at Google, Microsoft, Amazon, and leading tech startups.
Your goal is to transform weak, passive, or vague resume bullet points into compelling, recruiter-grade statements.

For every input bullet point, generate exactly 3 distinct rewrite variations:
1. "Metric-Driven (Quantified)": Uses Google's XYZ formula ("Accomplished [X] as measured by [Y] by doing [Z]"). Incorporates realistic, defensible engineering metrics (e.g. latency, throughput, test coverage, user scale, memory/CPU reduction).
2. "Technical Depth": Highlights systems architecture, core tech stack, design patterns, algorithmic optimization, concurrency, caching, databases, or cloud infrastructure.
3. "Leadership Impact": Emphasizes proactive ownership, agile delivery, cross-functional collaboration, code reviews, mentoring, and tangible team or product business impact.

Ensure output is strictly valid JSON matching the requested schema.
"""

BULLET_OPTIMIZER_PROMPT_TEMPLATE = """
Rewrite and optimize the following resume bullet point for target company '{company_name}' and role '{role_target}':

Original Bullet:
"{original_bullet}"

Context/Notes:
"{context}"

Return a valid JSON response strictly adhering to this structure:
{{
  "original_bullet": "{original_bullet}",
  "original_score": 55,
  "rewrites": [
    {{
      "flavor": "Metric-Driven (Quantified)",
      "flavor_id": "metric",
      "rewritten_bullet": "...",
      "impact_score_boost": 26,
      "action_verbs": ["Architected", "Reduced", "Accelerated"],
      "key_enhancement": "Explanation of the quantified improvement.",
      "diff_added": ["reduced API latency by 35%", "scaled to 10k+ requests/sec"]
    }},
    {{
      "flavor": "Technical Depth",
      "flavor_id": "technical",
      "rewritten_bullet": "...",
      "impact_score_boost": 24,
      "action_verbs": ["Engineered", "Implemented", "Containerized"],
      "key_enhancement": "Explanation of the technical and architectural depth added.",
      "diff_added": ["RESTful microservices", "Dockerized deployment pipeline"]
    }},
    {{
      "flavor": "Leadership Impact",
      "flavor_id": "leadership",
      "rewritten_bullet": "...",
      "impact_score_boost": 22,
      "action_verbs": ["Spearheaded", "Mentored", "Delivered"],
      "key_enhancement": "Explanation of ownership, initiative, and team velocity impact.",
      "diff_added": ["spearheaded feature delivery", "conducted peer code reviews"]
    }}
  ]
}}
Ensure the response is valid JSON only.
"""
