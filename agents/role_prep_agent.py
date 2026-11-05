"""
RolePreparationAgent - Role-Based Preparation Mode Agent
Generates comprehensive, role-specific placement preparation plans tailored
to the candidate's existing skills and identified skill gaps.

Supported Roles:
- Python Developer
- Data Analyst
- Data Scientist
- Software Engineer
"""

import json
import logging
from typing import Dict, Any, List, Optional
import config
from utils.gemini import generate_json_response

logger = logging.getLogger(__name__)

SUPPORTED_ROLES = [
    {
        "id": "software-engineer",
        "name": "Software Engineer",
        "icon": "fa-solid fa-code text-primary",
        "category": "Core Engineering & Systems",
        "tagline": "Data structures, scalable algorithms, system design, and software architecture."
    },
    {
        "id": "python-developer",
        "name": "Python Developer",
        "icon": "fa-brands fa-python text-warning",
        "category": "Backend & API Engineering",
        "tagline": "Backend services, asynchronous programming, APIs, and Python internals."
    },
    {
        "id": "data-analyst",
        "name": "Data Analyst",
        "icon": "fa-solid fa-chart-pie text-info",
        "category": "Data & Business Intelligence",
        "tagline": "Advanced SQL, data wrangling, dashboarding, metrics, and business insights."
    },
    {
        "id": "data-scientist",
        "name": "Data Scientist",
        "icon": "fa-solid fa-brain text-success",
        "category": "Machine Learning & AI",
        "tagline": "Statistical modeling, predictive algorithms, deep learning, NLP, and MLOps."
    }
]

ROLE_CATALOG: Dict[str, Dict[str, Any]] = {
    "Python Developer": {
        "title": "Python Developer",
        "tagline": "Backend engineering, API design, asynchronous processing, and high-performance Python application development.",
        "icon": "fa-brands fa-python text-warning",
        "color_class": "warning",
        "core_technologies": [
            {"name": "Python 3.12+", "category": "Language", "badge": "Core", "description": "Type hints, dataclasses, context managers, generators, and async/await syntax."},
            {"name": "FastAPI & Pydantic", "category": "Framework", "badge": "Essential", "description": "Modern high-performance async RESTful APIs with automated OpenAPI validation."},
            {"name": "Django & DRF", "category": "Framework", "badge": "Enterprise", "description": "Full-stack web framework with enterprise ORM, auth middleware, and migrations."},
            {"name": "PostgreSQL & SQLAlchemy", "category": "Database", "badge": "Database", "description": "Relational data modeling, connection pooling, and Alembic database versioning."},
            {"name": "Redis & Celery", "category": "Distributed Systems", "badge": "Async", "description": "Distributed task queues, background worker pools, caching, and rate limiting."},
            {"name": "Docker & Linux", "category": "DevOps", "badge": "Deployment", "description": "Containerized microservice packaging, multi-stage builds, and environment isolation."},
            {"name": "Pytest & Mocking", "category": "Testing", "badge": "Quality", "description": "Test-driven development, fixtures, parameterization, and integration testing."}
        ],
        "important_concepts": [
            {"concept": "Global Interpreter Lock (GIL) & Concurrency", "details": "Understanding threading CPU bottlenecks, multiprocessing shared memory, and asyncio event loops."},
            {"concept": "Python Data Model & Dunder Methods", "details": "Implementing custom classes with __iter__, __getitem__, __enter__, __exit__, and descriptors."},
            {"concept": "Memory Management & Garbage Collection", "details": "Reference counting mechanics, cyclic garbage collector, weakref, and memory profiling."},
            {"concept": "RESTful API Architecture & Security", "details": "Stateless design, OAuth2 / JWT authentication, rate limiting, and CORS headers."},
            {"concept": "ORM Query Optimization & N+1 Prevention", "details": "Avoiding lazy loading query storms using joinedload, selectinload, and raw SQL profiling."}
        ],
        "technical_topics": [
            {
                "topic": "Python Internals, Advanced OOP & Metaclasses",
                "importance": "High",
                "estimated_hours": 10,
                "skills": ["Python", "Object-Oriented Programming", "Metaclasses", "Descriptors"],
                "summary": "Deep dive into Python's object model, memory layout, custom descriptors, metaclasses, and functional idioms."
            },
            {
                "topic": "Asynchronous Programming with Asyncio",
                "importance": "High",
                "estimated_hours": 12,
                "skills": ["AsyncIO", "Concurrency", "Event Loops", "Coroutines"],
                "summary": "Mastering non-blocking I/O, TaskGroups, Semaphores, and asynchronous network clients."
            },
            {
                "topic": "Production REST API Design with FastAPI & Pydantic",
                "importance": "High",
                "estimated_hours": 14,
                "skills": ["FastAPI", "Pydantic", "REST APIs", "Swagger"],
                "summary": "Building scalable async endpoints with dependency injection, JWT authentication, and automated validation."
            },
            {
                "topic": "Relational Modeling & SQLAlchemy Optimization",
                "importance": "Medium",
                "estimated_hours": 12,
                "skills": ["SQL", "SQLAlchemy", "PostgreSQL", "Database Indexing"],
                "summary": "Constructing robust ORM schemas, migration pipelines with Alembic, and preventing N+1 queries."
            },
            {
                "topic": "Distributed Background Tasks with Celery & Redis",
                "importance": "Medium",
                "estimated_hours": 10,
                "skills": ["Celery", "Redis", "Message Queues", "Distributed Systems"],
                "summary": "Setting up asynchronous worker queues, scheduled beat tasks, dead-letter retries, and cache invalidation."
            },
            {
                "topic": "Automated Testing, Docker Containerization & CI/CD",
                "importance": "Medium",
                "estimated_hours": 8,
                "skills": ["Pytest", "Docker", "CI/CD", "Linux"],
                "summary": "Writing unit/integration tests with Pytest fixtures, building slim multi-stage Docker images, and GitHub Actions."
            }
        ],
        "coding_questions": [
            {
                "title": "Custom LRU Cache in Python",
                "difficulty": "Medium",
                "platform": "LeetCode",
                "topic": "Hash Map & Doubly Linked List",
                "skills_targeted": ["Python", "Data Structures", "OOP", "Caching"],
                "practice_url": "https://leetcode.com/problems/lru-cache/",
                "description": "Design a data structure that follows the constraints of a Least Recently Used (LRU) cache with O(1) get and put operations.",
                "hints": ["Use a hash map pointing to doubly linked list nodes for O(1) removals and head updates."]
            },
            {
                "title": "Flatten Deeply Nested Dictionary / JSON",
                "difficulty": "Medium",
                "platform": "Interview Challenge",
                "topic": "Recursion & Data Transformation",
                "skills_targeted": ["Python", "Recursion", "Generators", "JSON"],
                "practice_url": "https://leetcode.com/problems/flatten-nested-list-iterator/",
                "description": "Write a Python function or generator that converts an arbitrarily nested dict into a flat dict with dot-separated keys.",
                "hints": ["Recurse on dict values, passing an accumulated key prefix. Yield base cases directly."]
            },
            {
                "title": "Async Batch Request Queue with Rate Limiting",
                "difficulty": "Medium",
                "platform": "Practical Backend Challenge",
                "topic": "AsyncIO & Concurrency",
                "skills_targeted": ["AsyncIO", "Concurrency", "HTTP", "Python"],
                "practice_url": "https://github.com/topics/asyncio",
                "description": "Implement an asynchronous batch worker using asyncio.Queue and asyncio.Semaphore that fetches 100 API endpoints without exceeding 5 requests per second.",
                "hints": ["Use an asyncio.Semaphore(5) and asyncio.sleep() token bucket regulator."]
            },
            {
                "title": "Top K Frequent Words with Custom Sorting",
                "difficulty": "Medium",
                "platform": "LeetCode",
                "topic": "Heap & Hash Map",
                "skills_targeted": ["Python", "Heap", "Hash Map", "String Manipulation"],
                "practice_url": "https://leetcode.com/problems/top-k-frequent-words/",
                "description": "Given an array of strings words and an integer k, return the k most frequent strings sorted by frequency and lexicographical order.",
                "hints": ["Use collections.Counter and heapq.nsmallest with a custom comparator or inverted frequency tuple."]
            },
            {
                "title": "Encode and Decode Strings Without Delimiter Collisions",
                "difficulty": "Medium",
                "platform": "LeetCode",
                "topic": "String Manipulation & Design",
                "skills_targeted": ["Python", "String Parsing", "Algorithms"],
                "practice_url": "https://leetcode.com/problems/encode-and-decode-strings/",
                "description": "Design an algorithm to encode a list of strings to a single string and decode that string back to the original list.",
                "hints": ["Prefix each string with its length and a delimiter character (e.g., '4#love5#coder')."]
            }
        ],
        "roadmap": [
            {
                "week": "Week 1",
                "focus": "Python Internals, Idiomatic Syntax & Advanced OOP",
                "topics": ["Dunder methods & Python Data Model", "Generators, Iterators & itertools", "Decorators & Closures", "Type annotations with typing & Pydantic"],
                "coding_practice": ["Implement custom LRU Cache in Python", "Write a Generator-based log stream parser", "Matrix transpose and manipulation using list comprehensions"],
                "mini_projects": ["CLI Task Manager with JSON persistence and custom validation decorators"],
                "interview_questions": ["Explain how Python's GIL works and how it affects CPU vs I/O bound workloads.", "What is the difference between shallow and deep copy in Python?"],
                "revision_tasks": ["Review memory profiling with tracemalloc and object reference counts."],
                "estimated_hours": 12
            },
            {
                "week": "Week 2",
                "focus": "Concurrency, Threading & Asynchronous Programming",
                "topics": ["AsyncIO fundamentals & Event Loops", "Coroutines, Tasks & TaskGroups", "Threading vs Multiprocessing in Python", "Thread-safe data structures with queue.Queue"],
                "coding_practice": ["Build an asynchronous batch HTTP scraper using aiohttp", "Producer-Consumer pipeline with asyncio.Queue", "Multi-process CPU prime number sieve"],
                "mini_projects": ["Asynchronous Stock Price Poller with rate limiting and retry backoff"],
                "interview_questions": ["When should you use asyncio versus multiprocessing in Python?", "What happens if a synchronous blocking call is executed inside an async coroutine?"],
                "revision_tasks": ["Benchmark latency differences between synchronous requests and async aiohttp."],
                "estimated_hours": 14
            },
            {
                "week": "Week 3",
                "focus": "Modern RESTful Microservices with FastAPI",
                "topics": ["FastAPI routing, path & query parameters", "Pydantic V2 data models & custom validators", "Dependency injection system", "JWT Authentication & password hashing with bcrypt"],
                "coding_practice": ["Build an authenticated CRUD service for user accounts", "Custom error handling middleware with request logging", "File upload endpoint with MIME type validation"],
                "mini_projects": ["Secure Note Taking REST API with JWT Auth and Swagger documentation"],
                "interview_questions": ["How does FastAPI achieve high performance compared to Flask or Django?", "How do dependency injection functions work in FastAPI?"],
                "revision_tasks": ["Write integration tests using TestClient and pytest."],
                "estimated_hours": 14
            },
            {
                "week": "Week 4",
                "focus": "Relational Databases, SQLAlchemy & Redis Caching",
                "topics": ["SQLAlchemy 2.0 async sessions & ORM models", "Database migrations using Alembic", "PostgreSQL indexing & query execution plans", "Redis key-value caching & TTL expiration"],
                "coding_practice": ["Prevent N+1 query problem with joinedload/selectinload", "Cache expensive API endpoints using Redis and Python decorators", "Write complex multi-table joins in SQLAlchemy"],
                "mini_projects": ["E-Commerce Product Catalog API with PostgreSQL and Redis Caching layer"],
                "interview_questions": ["What is the N+1 query problem and how do you resolve it in SQLAlchemy?", "Explain Redis caching strategies (Cache-Aside, Write-Through)."],
                "revision_tasks": ["Inspect EXPLAIN ANALYZE on query plans in PostgreSQL."],
                "estimated_hours": 12
            },
            {
                "week": "Week 5",
                "focus": "Distributed Background Processing with Celery & Message Queues",
                "topics": ["Celery worker architecture with Redis/RabbitMQ broker", "Scheduled periodic tasks with Celery Beat", "Task chaining, groups, and chords", "Dead-letter queues & exponential retry policies"],
                "coding_practice": ["Implement a background PDF generator task with progress polling", "Email notification worker with automatic retries", "Distributed rate-limited worker"],
                "mini_projects": ["Automated Invoice Generation and Email Dispatch Microservice"],
                "interview_questions": ["How do distributed task queues handle worker crashes mid-task?", "What is an idempotent task in Celery and why is it important?"],
                "revision_tasks": ["Verify Redis broker queue depths and worker heartbeat logs."],
                "estimated_hours": 12
            },
            {
                "week": "Week 6",
                "focus": "Production Hardening, Containerization & Mock Interviews",
                "topics": ["Docker multi-stage builds for Python apps", "Production WSGI/ASGI servers (Gunicorn + Uvicorn)", "Environment configuration with python-dotenv & pydantic-settings", "Mock Technical Python Interview Rounds"],
                "coding_practice": ["Containerize the FastAPI + PostgreSQL + Redis application", "Write comprehensive Pytest suite with >85% branch coverage", "Solve 5 top LeetCode Python backend interview problems"],
                "mini_projects": ["Production-ready Docker Compose deployment of complete backend stack"],
                "interview_questions": ["Walk me through your production deployment process for a Python service.", "How do you diagnose and fix a memory leak in a running Python application?"],
                "revision_tasks": ["Run full test suite with coverage report and review common behavioral interview STAR stories."],
                "estimated_hours": 10
            }
        ]
    },

    "Data Analyst": {
        "title": "Data Analyst",
        "tagline": "Data modeling, advanced SQL queries, business intelligence dashboards, exploratory data analysis, and decision metrics.",
        "icon": "fa-solid fa-chart-pie text-info",
        "color_class": "info",
        "core_technologies": [
            {"name": "Advanced SQL", "category": "Querying", "badge": "Core", "description": "Window functions, CTEs, self-joins, aggregations, and query optimization."},
            {"name": "Python & Pandas", "category": "Data Wrangling", "badge": "Essential", "description": "DataFrame transformations, data cleansing, merging, and reshaping."},
            {"name": "Tableau / Power BI", "category": "Visualization", "badge": "BI", "description": "Interactive executive dashboards, DAX measures, drill-downs, and visual storytelling."},
            {"name": "Excel & Power Query", "category": "Spreadsheet", "badge": "Tool", "description": "Dynamic arrays, XLOOKUP, pivot tables, data modeling, and automated ETL."},
            {"name": "Dimensional Modeling", "category": "Architecture", "badge": "Design", "description": "Star schema, snowflake schema, fact vs dimension tables, and data normalization."},
            {"name": "Applied Statistics", "category": "Mathematics", "badge": "Analytics", "description": "Hypothesis testing, p-values, confidence intervals, and A/B test evaluation."}
        ],
        "important_concepts": [
            {"concept": "Analytical Window Functions", "details": "ROW_NUMBER, RANK, DENSE_RANK, NTILE, LAG/LEAD for partition calculations."},
            {"concept": "Common Table Expressions & Recursive Queries", "details": "Structuring complex multi-stage analytical queries with readability and efficiency."},
            {"concept": "Business & Product Metrics", "details": "Calculating Customer Acquisition Cost (CAC), Lifetime Value (LTV), Monthly Recurring Revenue (MRR), and Churn."},
            {"concept": "Cohort Analysis & Retention Curves", "details": "Tracking user behavior and engagement retention over monthly or weekly signup cohorts."},
            {"concept": "A/B Testing & Statistical Experimentation", "details": "Sample size determination, null hypothesis significance testing, and p-value interpretation."}
        ],
        "technical_topics": [
            {
                "topic": "Advanced SQL & Complex Analytical Querying",
                "importance": "High",
                "estimated_hours": 14,
                "skills": ["SQL", "PostgreSQL", "Window Functions", "CTEs"],
                "summary": "Mastering partition windows, ranking, moving averages, and multi-tier subqueries."
            },
            {
                "topic": "Data Cleaning & Manipulation with Pandas",
                "importance": "High",
                "estimated_hours": 12,
                "skills": ["Python", "Pandas", "NumPy", "Data Cleaning"],
                "summary": "Automating messy data ingestion, handling null values, type casting, and data reshaping."
            },
            {
                "topic": "Exploratory Data Analysis (EDA) & Descriptive Statistics",
                "importance": "High",
                "estimated_hours": 10,
                "skills": ["Statistics", "EDA", "Data Visualization", "Python"],
                "summary": "Analyzing distributions, correlation matrices, outlier detection, and summary statistics."
            },
            {
                "topic": "Executive BI Dashboarding with Tableau / Power BI",
                "importance": "Medium",
                "estimated_hours": 12,
                "skills": ["Tableau", "Power BI", "Data Visualization", "BI"],
                "summary": "Creating actionable dashboards with calculated fields, parameters, and drill-through actions."
            },
            {
                "topic": "Product & Growth Metrics Modeling",
                "importance": "Medium",
                "estimated_hours": 10,
                "skills": ["Product Analytics", "Cohort Analysis", "Business Metrics"],
                "summary": "Formulating key performance indicators: churn rate, retention cohorts, LTV, and conversion funnels."
            },
            {
                "topic": "Experimentation & A/B Testing Evaluation",
                "importance": "Medium",
                "estimated_hours": 8,
                "skills": ["A/B Testing", "Hypothesis Testing", "Statistics"],
                "summary": "Designing controlled experiments, checking statistical significance, and variance reduction."
            }
        ],
        "coding_questions": [
            {
                "title": "Top 3 Salaries per Department (Dense Rank)",
                "difficulty": "Medium",
                "platform": "LeetCode / HackerRank",
                "topic": "SQL Window Functions",
                "skills_targeted": ["SQL", "Window Functions", "PostgreSQL"],
                "practice_url": "https://leetcode.com/problems/department-top-three-salaries/",
                "description": "Find the employees who earn the top three unique salaries in each of the departments using DENSE_RANK() OVER (PARTITION BY ...).",
                "hints": ["Use a CTE with DENSE_RANK() partitioned by department and filter for ranking <= 3."]
            },
            {
                "title": "Consecutive Active Users / Daily Logins",
                "difficulty": "Medium",
                "platform": "LeetCode",
                "topic": "SQL Analytical Queries",
                "skills_targeted": ["SQL", "CTEs", "Data Analytics"],
                "practice_url": "https://leetcode.com/problems/consecutive-numbers/",
                "description": "Find all users who logged into the application for at least three consecutive days from an activity log table.",
                "hints": ["Use LAG() or date subtraction between row number and login date to identify consecutive blocks."]
            },
            {
                "title": "Cohort Retention & Churn Analysis in SQL/Pandas",
                "difficulty": "Medium",
                "platform": "StrataScratch",
                "topic": "Cohort Analytics",
                "skills_targeted": ["SQL", "Pandas", "Cohort Analysis", "Product Analytics"],
                "practice_url": "https://www.stratascratch.com/",
                "description": "Calculate the percentage of users who returned to make a purchase in month 1, month 2, and month 3 following their initial signup.",
                "hints": ["Find the first purchase date per user, calculate the month delta for subsequent purchases, and pivot."]
            },
            {
                "title": "Rolling 7-Day Moving Average Revenue",
                "difficulty": "Medium",
                "platform": "LeetCode / HackerRank",
                "topic": "SQL Window Frames",
                "skills_targeted": ["SQL", "Window Functions", "Time Series"],
                "practice_url": "https://leetcode.com/problems/restaurant-growth/",
                "description": "Compute moving average of how much the customer paid in a seven days window (current day + 6 days before).",
                "hints": ["Use AVG(daily_amount) OVER (ORDER BY visited_on ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)."]
            },
            {
                "title": "Pandas Automated Data Hygiene & Outlier Detection Pipeline",
                "difficulty": "Medium",
                "platform": "Practical Analytics Challenge",
                "topic": "Data Cleaning & Python",
                "skills_targeted": ["Python", "Pandas", "Data Cleaning", "Statistics"],
                "practice_url": "https://github.com/topics/pandas",
                "description": "Write a Pandas function that imputes missing values using group-wise medians and detects multivariate outliers using IQR bounds.",
                "hints": ["Group by category and apply transform(lambda x: x.fillna(x.median()))."]
            }
        ],
        "roadmap": [
            {
                "week": "Week 1",
                "focus": "Advanced SQL & Relational Querying Mastery",
                "topics": ["Window functions (ROW_NUMBER, RANK, DENSE_RANK, NTILE)", "Offset functions (LAG, LEAD)", "Common Table Expressions (CTEs) & Subqueries", "Conditional aggregations with CASE WHEN"],
                "coding_practice": ["Solve 5 LeetCode SQL Medium problems on Window Functions", "Query top performing sales reps per region", "Calculate year-over-year growth percentages"],
                "mini_projects": ["Complex SQL script calculating revenue breakdowns and active customer segments"],
                "interview_questions": ["What is the difference between RANK() and DENSE_RANK()?", "How does an INNER JOIN differ from a LEFT JOIN with a WHERE IS NULL condition?"],
                "revision_tasks": ["Review SQL query execution order: FROM -> WHERE -> GROUP BY -> HAVING -> SELECT -> WINDOW -> ORDER BY."],
                "estimated_hours": 12
            },
            {
                "week": "Week 2",
                "focus": "Python & Pandas Data Wrangling",
                "topics": ["Pandas Series & DataFrame indexing/slicing", "Handling null, duplicate, and malformed records", "Reshaping data with melt, pivot, and pivot_table", "DateTime parsing, timezones, and frequency resampling"],
                "coding_practice": ["Clean a raw CSV dataset with mixed types and missing dates", "Merge transaction data with user demographic records", "Compute customer-level purchase statistics"],
                "mini_projects": ["Automated Data Hygiene & Preprocessing Script for messy Excel/CSV dumps"],
                "interview_questions": ["What is the difference between apply() and transform() in Pandas?", "How does Pandas handle missing values internally?"],
                "revision_tasks": ["Benchmark vectorized Pandas operations against standard Python loops."],
                "estimated_hours": 12
            },
            {
                "week": "Week 3",
                "focus": "Exploratory Data Analysis & Inferential Statistics",
                "topics": ["Univariate and bivariate statistical analysis", "Measures of central tendency, dispersion, and skewness", "Correlation analysis (Pearson vs Spearman)", "Visualizations with Seaborn & Matplotlib (Boxplots, Histograms, Heatmaps)"],
                "coding_practice": ["Perform complete EDA on a retail transactions dataset", "Detect and document outlier patterns using IQR and Z-scores", "Plot correlation heatmaps and distribution curves"],
                "mini_projects": ["Comprehensive EDA Jupyter Notebook with executive findings and actionable charts"],
                "interview_questions": ["When should you use the median instead of the mean to represent central tendency?", "How do you detect if a dataset is normally distributed?"],
                "revision_tasks": ["Review Central Limit Theorem and standard error formulas."],
                "estimated_hours": 10
            },
            {
                "week": "Week 4",
                "focus": "Business Intelligence & Executive Dashboarding",
                "topics": ["Dashboard design principles and visual hierarchy", "Tableau / Power BI calculated fields & parameters", "Connecting to live SQL databases & automated refreshes", "Drill-down filters, actions, and KPI summary tiles"],
                "coding_practice": ["Build an interactive sales dashboard in Tableau / Power BI", "Implement dynamic date range filters (Last 30 Days, QTD, YTD)", "Create calculated fields for profit margins and target benchmarks"],
                "mini_projects": ["Interactive Executive Sales & Marketing Performance Dashboard"],
                "interview_questions": ["How do you choose between a bar chart, line chart, and scatter plot for business stakeholders?", "What are Level of Detail (LOD) expressions in Tableau?"],
                "revision_tasks": ["Publish dashboard to Tableau Public or export interactive PDF report."],
                "estimated_hours": 12
            },
            {
                "week": "Week 5",
                "focus": "Product Metrics, Cohort Analytics & A/B Testing",
                "topics": ["User acquisition, activation, retention, and churn funnels", "Building monthly cohort retention heatmaps in SQL & Pandas", "A/B test design: sample size, minimum detectable effect (MDE)", "Evaluating p-values, alpha/beta errors, and confidence intervals"],
                "coding_practice": ["Write SQL query to produce a triangular cohort retention matrix", "Conduct two-sample t-test on A/B test conversion rate data in Python", "Calculate customer lifetime value (LTV) curves"],
                "mini_projects": ["Cohort Retention Analysis & A/B Experiment Impact Report"],
                "interview_questions": ["If an A/B test has a p-value of 0.04, what does that mean in plain English to an engineering manager?", "What is survivorship bias and how does it manifest in cohort data?"],
                "revision_tasks": ["Calculate sample size requirements using Power Analysis formulas."],
                "estimated_hours": 12
            },
            {
                "week": "Week 6",
                "focus": "Business Case Studies, Portfolio Polish & Mock Interviews",
                "topics": ["Translating raw numbers into executive recommendations", "Building a GitHub / portfolio data analysis case study", "Common Data Analyst behavioral and scenario interview questions", "Live SQL whiteboard and timed analytical screening rounds"],
                "coding_practice": ["Solve 3 timed SQL interview prompts on StrataScratch / LeetCode", "Present your capstone dashboard with a 5-minute executive pitch", "Structure business case questions using MECE framework"],
                "mini_projects": ["Complete Data Analyst Portfolio Project with README, SQL scripts, and BI Dashboard"],
                "interview_questions": ["A key business metric dropped by 15% yesterday. Walk me through your root cause analysis.", "Tell me about a time your data analysis directly influenced a business decision."],
                "revision_tasks": ["Practice explaining data trade-offs clearly without technical jargon."],
                "estimated_hours": 10
            }
        ]
    },

    "Data Scientist": {
        "title": "Data Scientist",
        "tagline": "Statistical modeling, predictive machine learning, deep learning, NLP, feature engineering, and MLOps deployment.",
        "icon": "fa-solid fa-brain text-success",
        "color_class": "success",
        "core_technologies": [
            {"name": "Python & Scikit-Learn", "category": "Machine Learning", "badge": "Core", "description": "Supervised/unsupervised algorithms, preprocessing pipelines, and model evaluation."},
            {"name": "PyTorch / TensorFlow", "category": "Deep Learning", "badge": "Neural", "description": "Neural network architectures, autograd, backpropagation, and GPU training."},
            {"name": "XGBoost & LightGBM", "category": "Ensemble ML", "badge": "Essential", "description": "Gradient boosted decision trees with custom loss functions and Optuna tuning."},
            {"name": "Hugging Face & NLP", "category": "NLP / LLMs", "badge": "Modern", "description": "Pretrained transformers, BERT, embeddings, and generative AI fine-tuning."},
            {"name": "MLflow & DVC", "category": "MLOps", "badge": "Production", "description": "Experiment tracking, model registry, dataset versioning, and artifact storage."},
            {"name": "Linear Algebra & Stats", "category": "Mathematics", "badge": "Theory", "description": "Eigenvalues, SVD, probability distributions, maximum likelihood estimation."}
        ],
        "important_concepts": [
            {"concept": "Bias-Variance Tradeoff & Regularization", "details": "Balancing underfitting vs overfitting via L1 Lasso, L2 Ridge, and ElasticNet penalties."},
            {"concept": "Evaluation Metrics Beyond Accuracy", "details": "ROC-AUC, Precision-Recall curves, F1-Score, Cohen's Kappa, Log-Loss for imbalanced data."},
            {"concept": "Cross-Validation & Data Leakage Prevention", "details": "K-Fold, Stratified K-Fold, TimeSeriesSplit, and keeping transformation statistics inside training folds."},
            {"concept": "Feature Engineering & Imbalance Handling", "details": "Target encoding, interaction features, SMOTE oversampling, and class weighting."},
            {"concept": "Gradient Descent & Backpropagation", "details": "Stochastic gradient descent (SGD), Adam optimizer, learning rate schedules, and chain rule derivatives."}
        ],
        "technical_topics": [
            {
                "topic": "Mathematical Foundations for Data Science",
                "importance": "High",
                "estimated_hours": 12,
                "skills": ["Linear Algebra", "Calculus", "Probability", "Statistics"],
                "summary": "Matrix operations, eigenvalues/eigenvectors, SVD, gradient vectors, and probability densities."
            },
            {
                "topic": "Supervised Learning & Ensemble Modeling",
                "importance": "High",
                "estimated_hours": 14,
                "skills": ["Machine Learning", "Scikit-Learn", "XGBoost", "Random Forest"],
                "summary": "Mastering regression, classification, decision trees, random forests, and gradient boosting."
            },
            {
                "topic": "Feature Engineering & Preprocessing Pipelines",
                "importance": "High",
                "estimated_hours": 12,
                "skills": ["Feature Engineering", "Pandas", "Scikit-Learn", "Pipelines"],
                "summary": "Constructing leakage-free ColumnTransformers, handling categorical encodings, scaling, and PCA."
            },
            {
                "topic": "Deep Learning Fundamentals with PyTorch",
                "importance": "Medium",
                "estimated_hours": 14,
                "skills": ["Deep Learning", "PyTorch", "Neural Networks", "Tensors"],
                "summary": "Building neural architectures from scratch: feedforward nets, convolutional layers, and optimizers."
            },
            {
                "topic": "Natural Language Processing & Transformer Models",
                "importance": "Medium",
                "estimated_hours": 12,
                "skills": ["NLP", "Hugging Face", "Transformers", "Embeddings"],
                "summary": "Text tokenization, TF-IDF, Word2Vec, BERT embeddings, and transformer attention mechanisms."
            },
            {
                "topic": "Model Evaluation, Experiment Tracking & MLOps",
                "importance": "Medium",
                "estimated_hours": 10,
                "skills": ["MLOps", "MLflow", "Model Evaluation", "Docker"],
                "summary": "Tracking experiments with MLflow, hyperparameter tuning with Optuna, and deploying models with FastAPI."
            }
        ],
        "coding_questions": [
            {
                "title": "Implement Linear Regression with Gradient Descent from Scratch",
                "difficulty": "Medium",
                "platform": "ML Coding Challenge",
                "topic": "Machine Learning from Scratch",
                "skills_targeted": ["Python", "NumPy", "Linear Algebra", "Optimization"],
                "practice_url": "https://github.com/topics/machine-learning",
                "description": "Implement a class LinearRegressionUsingGD in pure NumPy with fit(), predict(), loss computation, and learning rate parameter updates without using scikit-learn.",
                "hints": ["Gradient of MSE loss w.r.t weights is (-2/N) * X.T @ (y - y_pred)."]
            },
            {
                "title": "K-Means Clustering Algorithm from Scratch",
                "difficulty": "Medium",
                "platform": "ML Coding Challenge",
                "topic": "Unsupervised Learning",
                "skills_targeted": ["Python", "NumPy", "K-Means", "Unsupervised Learning"],
                "practice_url": "https://github.com/topics/machine-learning",
                "description": "Write a vectorized K-Means clustering algorithm in NumPy that iteratively updates cluster centroids until convergence tolerance is satisfied.",
                "hints": ["Compute Euclidean distances using np.linalg.norm or broadcasting, assign labels via np.argmin, and compute cluster means."]
            },
            {
                "title": "Compute Precision, Recall, and ROC-AUC Curves",
                "difficulty": "Medium",
                "platform": "ML Evaluation Challenge",
                "topic": "Model Metrics",
                "skills_targeted": ["Statistics", "Python", "NumPy", "Model Evaluation"],
                "practice_url": "https://github.com/topics/scikit-learn",
                "description": "Given ground truth binary labels and predicted probability scores, write functions to compute Precision, Recall, and ROC-AUC without calling sklearn.metrics.",
                "hints": ["Sort samples by predicted score descending. Iterate through threshold points and update TP, FP, TN, FN."]
            },
            {
                "title": "TF-IDF Matrix & Cosine Similarity Text Matcher",
                "difficulty": "Medium",
                "platform": "NLP Challenge",
                "topic": "Natural Language Processing",
                "skills_targeted": ["NLP", "Python", "String Manipulation", "Linear Algebra"],
                "practice_url": "https://github.com/topics/nlp",
                "description": "Build a simple document search engine that tokenizes documents, calculates TF-IDF scores, and ranks documents by cosine similarity against an input query.",
                "hints": ["TF = term count / total terms in doc; IDF = log((1 + N) / (1 + doc_freq)) + 1; Cosine similarity = dot(A, B) / (norm(A) * norm(B))."]
            },
            {
                "title": "Stratified K-Fold Cross Validation Splitter",
                "difficulty": "Medium",
                "platform": "Scikit-Learn Architecture",
                "topic": "Cross Validation",
                "skills_targeted": ["Python", "NumPy", "Algorithms"],
                "practice_url": "https://github.com/topics/scikit-learn",
                "description": "Implement a generator function stratified_k_fold(X, y, n_splits=5) that returns train_idx and test_idx preserving class balance across folds.",
                "hints": ["Group indices by class, split each class into n_splits chunks, and recombine chunks per fold."]
            }
        ],
        "roadmap": [
            {
                "week": "Week 1",
                "focus": "Mathematical Foundations & NumPy Vectorization",
                "topics": ["Linear algebra: Matrix multiplications, dot products, eigenvalues, SVD", "Multivariate calculus: Gradients, partial derivatives, chain rule", "Probability distributions: Normal, binomial, Poisson, Bayes' theorem", "Vectorized computing with NumPy broadcasting and array manipulation"],
                "coding_practice": ["Implement Linear Regression with Gradient Descent from Scratch in NumPy", "Matrix multiplication and SVD implementation", "Compute probability density functions and cumulative distributions"],
                "mini_projects": ["Pure NumPy Gradient Descent Optimization Suite with visual loss curves"],
                "interview_questions": ["What is an eigenvector and eigenvalue, and how does PCA use them?", "Explain the difference between L1 (Lasso) and L2 (Ridge) regularization mathematically."],
                "revision_tasks": ["Derive the closed-form normal equation for Linear Regression: (X^T X)^-1 X^T y."],
                "estimated_hours": 12
            },
            {
                "week": "Week 2",
                "focus": "Supervised Learning & Scikit-Learn Pipelines",
                "topics": ["Classification algorithms: Logistic Regression, SVM, Decision Trees", "Ensemble methods: Bagging, Random Forests, AdaBoost", "Feature scaling: StandardScaler, RobustScaler, MinMaxScaler", "Building modular ML pipelines with ColumnTransformer"],
                "coding_practice": ["Build an end-to-end customer churn classification pipeline", "Tune hyper-parameters using GridSearchCV and RandomizedSearchCV", "Evaluate models with Confusion Matrices and ROC-AUC curves"],
                "mini_projects": ["Predictive Loan Default Classification Pipeline with leakage-free ColumnTransformer"],
                "interview_questions": ["How does a Random Forest reduce variance without increasing bias?", "What is data leakage and how do you prevent it when scaling features?"],
                "revision_tasks": ["Compare decision tree split criteria: Gini Impurity vs Entropy."],
                "estimated_hours": 14
            },
            {
                "week": "Week 3",
                "focus": "Advanced Gradient Boosting (XGBoost / LightGBM) & Imbalanced Data",
                "topics": ["Gradient Boosting mechanics: residuals, learning rate, tree shrinkage", "XGBoost and LightGBM implementations and advantages", "Handling class imbalance: SMOTE, class_weight, focal loss", "Hyperparameter optimization with Optuna Bayesian search"],
                "coding_practice": ["Train and tune XGBoost classifier on heavily imbalanced fraud detection dataset", "Implement SMOTE oversampling inside an imbalanced-learn pipeline", "Evaluate Precision-Recall curves and optimal decision thresholds"],
                "mini_projects": ["Credit Card Fraud Detection System with XGBoost, SMOTE, and Optuna tuning"],
                "interview_questions": ["How does Gradient Boosting differ fundamentally from Random Forests?", "Why is accuracy a misleading metric for imbalanced classification?"],
                "revision_tasks": ["Benchmark training speed and memory footprints of XGBoost vs LightGBM."],
                "estimated_hours": 14
            },
            {
                "week": "Week 4",
                "focus": "Deep Learning Fundamentals with PyTorch",
                "topics": ["Tensors, computation graphs, and autograd in PyTorch", "Building Multi-Layer Perceptrons (MLP) with torch.nn", "Loss functions: CrossEntropyLoss, MSELoss, BCEWithLogitsLoss", "Optimizers (Adam, SGD with momentum) and training loop mechanics"],
                "coding_practice": ["Build and train a custom neural network on MNIST / tabular data in PyTorch", "Implement custom dataset and DataLoader with batch shuffling", "Add dropout, batch normalization, and early stopping"],
                "mini_projects": ["PyTorch Neural Network Classifier for Image / Complex Tabular Data"],
                "interview_questions": ["What is vanishing gradient problem and how does ReLU / residual connections mitigate it?", "Explain the difference between epoch, batch size, and iteration."],
                "revision_tasks": ["Inspect gradient norms during backpropagation to verify stability."],
                "estimated_hours": 14
            },
            {
                "week": "Week 5",
                "focus": "Modern NLP, Transformers & LLM Foundations",
                "topics": ["Text tokenization: WordPiece, BPE, Byte-level BPE", "Word embeddings: Word2Vec, GloVe, dense vector spaces", "Transformer architecture: Self-attention, multi-head attention, positional encoding", "Using Hugging Face Transformers for sentiment analysis and embeddings"],
                "coding_practice": ["Implement a TF-IDF text similarity search engine from scratch", "Extract sentence embeddings using Hugging Face sentence-transformers", "Fine-tune a pretrained BERT model for text classification"],
                "mini_projects": ["Semantic Resume / Job Description Matcher using Transformer Embeddings"],
                "interview_questions": ["How does the self-attention mechanism calculate attention weights between tokens?", "What is the difference between BERT (encoder) and GPT (decoder) architectures?"],
                "revision_tasks": ["Calculate scaled dot-product attention equation: softmax(Q K^T / sqrt(d_k)) V."],
                "estimated_hours": 14
            },
            {
                "week": "Week 6",
                "focus": "MLOps, Model Serving & Data Science Interviews",
                "topics": ["Tracking ML experiments and parameters with MLflow", "Packaging machine learning models into Docker containers", "Serving real-time inference endpoints with FastAPI", "Mock Data Science Technical and Portfolio Review Interviews"],
                "coding_practice": ["Export trained model with Joblib/ONNX and serve with FastAPI", "Log model metrics and artifacts to local MLflow tracking server", "Answer 10 common Data Science conceptual interview questions"],
                "mini_projects": ["Production-ready ML Inference Microservice with Docker and Swagger Docs"],
                "interview_questions": ["How do you detect and handle model concept drift in production?", "Walk me through how you would frame and solve a business problem using machine learning."],
                "revision_tasks": ["Prepare a 5-minute walkthrough of your best ML project highlighting metric gains."],
                "estimated_hours": 10
            }
        ]
    },

    "Software Engineer": {
        "title": "Software Engineer",
        "tagline": "Core data structures, scalable algorithms, object-oriented system design, concurrency, and robust software architecture.",
        "icon": "fa-solid fa-code text-primary",
        "color_class": "primary",
        "core_technologies": [
            {"name": "Languages (Java/C++/Python)", "category": "Core Language", "badge": "Core", "description": "Strong proficiency in modern object-oriented language syntax, STL, and memory management."},
            {"name": "Data Structures & Algos", "category": "Computer Science", "badge": "Essential", "description": "Arrays, Trees, Graphs, Dynamic Programming, Heaps, and asymptotic complexity."},
            {"name": "System Design Fundamentals", "category": "Architecture", "badge": "Design", "description": "Load balancers, caching, database sharding, CAP theorem, and microservices."},
            {"name": "Databases & Indexing", "category": "Data Storage", "badge": "Database", "description": "PostgreSQL, MySQL, B-Tree indexes, transactions, and ACID properties."},
            {"name": "Git & CI/CD Pipelines", "category": "DevOps", "badge": "Workflow", "description": "Version control, branching strategies, automated testing, and deployment pipelines."},
            {"name": "Operating Systems & Networking", "category": "Systems", "badge": "CS Fundamentals", "description": "Threads, processes, locks, TCP/IP, sockets, and HTTP/2 protocol."}
        ],
        "important_concepts": [
            {"concept": "Asymptotic Analysis (Big-O Notation)", "details": "Analyzing time and space complexities across worst, average, and amortized cases."},
            {"concept": "SOLID Design Principles & OOP Patterns", "details": "Single responsibility, open-closed, Liskov substitution, interface segregation, and dependency inversion."},
            {"concept": "Scalable System Design Fundamentals", "details": "Horizontal scaling, CDN edge caching, message queues, and rate limiters."},
            {"concept": "Concurrency, Thread Safety & Deadlocks", "details": "Critical sections, mutexes, semaphores, race conditions, and synchronization primitives."},
            {"concept": "Relational Indexing & Database Normalization", "details": "Clustered vs non-clustered indexes, composite keys, and B+ Tree traversals."}
        ],
        "technical_topics": [
            {
                "topic": "Data Structures & Algorithmic Complexity",
                "importance": "High",
                "estimated_hours": 16,
                "skills": ["Algorithms", "Data Structures", "Big-O", "Problem Solving"],
                "summary": "Deep mastery of Arrays, Linked Lists, Binary Trees, Graphs, Heaps, and Hash Maps."
            },
            {
                "topic": "Object-Oriented Design & SOLID Architecture",
                "importance": "High",
                "estimated_hours": 12,
                "skills": ["OOP", "Design Patterns", "SOLID", "Clean Code"],
                "summary": "Writing modular, testable code applying Factory, Observer, Strategy, and Singleton patterns."
            },
            {
                "topic": "High-Level & Low-Level System Design",
                "importance": "High",
                "estimated_hours": 14,
                "skills": ["System Design", "Scalability", "Microservices", "Caching"],
                "summary": "Architecting scalable systems: URL shortener, rate limiter, chat application, and caching tiers."
            },
            {
                "topic": "Database Internals & Transaction Management",
                "importance": "Medium",
                "estimated_hours": 10,
                "skills": ["SQL", "Databases", "ACID", "Transactions"],
                "summary": "Transaction isolation levels, WAL logs, index optimization, and distributed database sharding."
            },
            {
                "topic": "Operating Systems, Concurrency & Networking",
                "importance": "Medium",
                "estimated_hours": 10,
                "skills": ["Operating Systems", "Networking", "Concurrency", "Linux"],
                "summary": "Processes vs threads, virtual memory, context switching, TCP handshake, and HTTP protocols."
            },
            {
                "topic": "Modern Development Workflow, Docker & Testing",
                "importance": "Medium",
                "estimated_hours": 8,
                "skills": ["Git", "Docker", "Testing", "CI/CD"],
                "summary": "Containerization, Git workflows, unit/integration testing harnesses, and CI automation."
            }
        ],
        "coding_questions": [
            {
                "title": "Two Sum & Pair Lookup Optimization",
                "difficulty": "Easy",
                "platform": "LeetCode",
                "topic": "Arrays & Hash Map",
                "skills_targeted": ["Arrays", "Hash Map", "Lookup Optimization"],
                "practice_url": "https://leetcode.com/problems/two-sum/",
                "description": "Given an array of integers nums and an integer target, return indices of the two numbers such that they add up to target.",
                "hints": ["Use a hash table to store visited numbers and their index for O(1) lookups."]
            },
            {
                "title": "Longest Substring Without Repeating Characters",
                "difficulty": "Medium",
                "platform": "LeetCode",
                "topic": "Sliding Window",
                "skills_targeted": ["Sliding Window", "Two Pointers", "String", "Hash Set"],
                "practice_url": "https://leetcode.com/problems/longest-substring-without-repeating-characters/",
                "description": "Given a string s, find the length of the longest substring without duplicate characters.",
                "hints": ["Maintain a sliding window [left, right] and update character last-seen index."]
            },
            {
                "title": "Number of Islands (BFS / DFS Graph Traversal)",
                "difficulty": "Medium",
                "platform": "LeetCode",
                "topic": "Graphs & BFS/DFS",
                "skills_targeted": ["Graphs", "BFS", "DFS", "Matrix"],
                "practice_url": "https://leetcode.com/problems/number-of-islands/",
                "description": "Given an m x n 2D binary grid which represents a map of '1's (land) and '0's (water), return the number of islands.",
                "hints": ["Iterate through every cell. When '1' is encountered, trigger BFS/DFS to sink the island."]
            },
            {
                "title": "Lowest Common Ancestor of a Binary Tree",
                "difficulty": "Medium",
                "platform": "LeetCode",
                "topic": "Binary Trees",
                "skills_targeted": ["Binary Trees", "Recursion", "DFS", "Tree Traversal"],
                "practice_url": "https://leetcode.com/problems/lowest-common-ancestor-of-a-binary-tree/",
                "description": "Given a binary tree, find the lowest common ancestor (LCA) of two given nodes in the tree.",
                "hints": ["Traverse recursively. If root is p or q or left/right branches return targets, current node is LCA."]
            },
            {
                "title": "Coin Change (Dynamic Programming)",
                "difficulty": "Medium",
                "platform": "LeetCode",
                "topic": "Dynamic Programming",
                "skills_targeted": ["Dynamic Programming", "Knapsack", "Optimization"],
                "practice_url": "https://leetcode.com/problems/coin-change/",
                "description": "Find the fewest number of coins that you need to make up that amount from given denominations.",
                "hints": ["Define dp[i] as min coins to form amount i. dp[i] = min(dp[i - coin] + 1)."]
            },
            {
                "title": "Course Schedule II (Topological Sort)",
                "difficulty": "Medium",
                "platform": "LeetCode",
                "topic": "Graphs & Topological Sort",
                "skills_targeted": ["Graphs", "Topological Sort", "DAG", "Cycle Detection"],
                "practice_url": "https://leetcode.com/problems/course-schedule-ii/",
                "description": "Return the ordering of courses you should finish to complete all courses given their prerequisites.",
                "hints": ["Use Kahn's algorithm with in-degree array and queue of 0 in-degree nodes."]
            }
        ],
        "roadmap": [
            {
                "week": "Week 1",
                "focus": "Core Data Structures & Algorithmic Patterns (Arrays, Strings, Hash Maps)",
                "topics": ["Asymptotic complexity analysis (Big-O)", "Two Pointers & Sliding Window techniques", "Prefix Sums & Hash Table optimizations", "Fast and Slow Pointers on Linked Lists"],
                "coding_practice": ["Solve Two Sum & 3Sum", "Longest Substring Without Repeating Characters", "Linked List Cycle detection and reversal"],
                "mini_projects": ["In-memory Cache with eviction policy and constant time lookups"],
                "interview_questions": ["Explain how a Hash Table handles collisions (Chaining vs Open Addressing).", "What is the difference between average-case and worst-case time complexity?"],
                "revision_tasks": ["Review time and space complexity table for all primitive operations."],
                "estimated_hours": 14
            },
            {
                "week": "Week 2",
                "focus": "Trees, Heaps, Binary Search & Recursive Problem Solving",
                "topics": ["Binary Search on sorted arrays & monotonic answer spaces", "Binary Tree traversals (In-order, Pre-order, Post-order, Level-order)", "Binary Search Trees (BST) validation and insertion", "Min-Heap & Max-Heap operations with PriorityQueue"],
                "coding_practice": ["Lowest Common Ancestor of a Binary Tree", "Kth Largest Element in an Array using Heap", "Search in Rotated Sorted Array"],
                "mini_projects": ["Auto-complete Trie search engine with frequency ranking"],
                "interview_questions": ["How does a balanced BST (like Red-Black Tree) maintain O(log N) lookup height?", "When is Binary Search applicable beyond simple sorted arrays?"],
                "revision_tasks": ["Practice writing iterative and recursive tree traversals."],
                "estimated_hours": 14
            },
            {
                "week": "Week 3",
                "focus": "Graphs (BFS, DFS, Topological Sort) & Backtracking",
                "topics": ["Graph representations: Adjacency list vs adjacency matrix", "Breadth-First Search (BFS) for shortest unweighted paths", "Depth-First Search (DFS) & Connected Components", "Topological Sort using Kahn's algorithm and cycle detection"],
                "coding_practice": ["Number of Islands on 2D matrix", "Course Schedule I & II", "Word Ladder / Shortest Transformation Sequence"],
                "mini_projects": ["Dependency Resolver & Build Task Scheduler using Topological Sort"],
                "interview_questions": ["What is the time complexity of BFS on an adjacency list graph?", "How do you detect a cycle in a directed graph versus an undirected graph?"],
                "revision_tasks": ["Implement Disjoint Set Union (Union-Find) with path compression."],
                "estimated_hours": 16
            },
            {
                "week": "Week 4",
                "focus": "Dynamic Programming & Optimization Techniques",
                "topics": ["Memoization (Top-down) vs Tabulation (Bottom-up)", "1D Dynamic Programming: Climbing Stairs, House Robber", "2D DP & Knapsack problems: 0/1 Knapsack, Coin Change", "Longest Common Subsequence & Longest Increasing Subsequence"],
                "coding_practice": ["Coin Change & Coin Change II", "Longest Increasing Subsequence in O(N log N)", "Edit Distance between two strings"],
                "mini_projects": ["Resource Allocator & Knapsack Optimization Engine"],
                "interview_questions": ["How do you identify if a problem has optimal substructure and overlapping subproblems?", "What is the difference between greedy algorithms and dynamic programming?"],
                "revision_tasks": ["Re-solve 3 classic DP problems by drawing state transition tables."],
                "estimated_hours": 16
            },
            {
                "week": "Week 5",
                "focus": "System Design Fundamentals & Object-Oriented Architecture",
                "topics": ["Scalability basics: Vertical vs horizontal scaling, load balancers", "Caching strategies (Redis, Memcached, CDN)", "Database sharding, replication, and CAP Theorem", "Low-Level Design: SOLID principles and Design Patterns"],
                "coding_practice": ["Design a Rate Limiter (Token Bucket / Leaky Bucket)", "Design a URL Shortener (TinyURL) with high throughput", "Implement Parking Lot or Movie Ticket Booking Low-Level System"],
                "mini_projects": ["Scalable URL Shortener System with Redis Caching and Hash IDs"],
                "interview_questions": ["Explain the CAP theorem and give examples of CP and AP systems.", "How does a distributed cache like Redis prevent cache stampedes?"],
                "revision_tasks": ["Review database indexing (B+ Trees) and query execution plans."],
                "estimated_hours": 14
            },
            {
                "week": "Week 6",
                "focus": "Full Interview Simulation, Behavioral STAR & Capstone Polish",
                "topics": ["Mock Technical Coding Rounds under timed constraints", "Behavioral Interview prep using STAR method (Situation, Task, Action, Result)", "Questions to ask your interviewer at the end of the round", "Final Resume & Portfolio check"],
                "coding_practice": ["Complete 3 timed 45-minute LeetCode mock interview assessments", "Practice verbalizing thought process and space/time tradeoffs", "Refactor and document top GitHub repositories"],
                "mini_projects": ["Comprehensive Software Engineering Capstone Portfolio Ready for Campus Drives"],
                "interview_questions": ["Tell me about a complex technical bug you investigated and how you resolved it.", "Describe a situation where you had to make a tradeoff between speed and code quality."],
                "revision_tasks": ["Conduct a peer mock interview and rehearse your self-introduction elevator pitch."],
                "estimated_hours": 10
            }
        ]
    }
}


class RolePreparationAgent:
    """
    Agent orchestrating the Role-Based Preparation Mode.
    Produces personalized technical topics, coding questions, technology stacks,
    and structured roadmaps according to the selected role.
    """

    def __init__(self) -> None:
        pass

    def get_supported_roles(self) -> List[Dict[str, Any]]:
        """Returns metadata for all available preparation roles."""
        return SUPPORTED_ROLES

    def normalize_role_name(self, raw_role: Optional[str]) -> str:
        """Normalizes free-form role strings to a canonical role name."""
        if not raw_role:
            return "Software Engineer"
        norm = str(raw_role).strip().lower()

        if "python" in norm:
            return "Python Developer"
        elif "analyst" in norm or "analytics" in norm or "bi " in norm or "business intelligence" in norm:
            return "Data Analyst"
        elif "scientist" in norm or "machine learning" in norm or "ml " in norm or "ai " in norm:
            return "Data Scientist"
        elif "software" in norm or "sde" in norm or "swe" in norm or "engineer" in norm or "developer" in norm:
            return "Software Engineer"
        return "Software Engineer"

    def generate_role_preparation(
        self,
        target_role: str,
        existing_skills: Optional[List[str]] = None,
        skill_gaps: Optional[List[str]] = None,
        company_name: Optional[str] = None,
        resume_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generates role-specific preparation content personalized with the candidate's skills and gaps.
        """
        canonical_role = self.normalize_role_name(target_role)
        role_data = ROLE_CATALOG.get(canonical_role, ROLE_CATALOG["Software Engineer"])

        existing_skills = [s.strip() for s in (existing_skills or []) if str(s).strip()]
        skill_gaps = [s.strip() for s in (skill_gaps or []) if str(s).strip()]
        company = (company_name or "General Campus Recruitment").strip()

        # Deduplicate skills
        existing_skills_lower = {s.lower() for s in existing_skills}
        skill_gaps_lower = {s.lower() for s in skill_gaps}

        # 1. Identify bridged skill gaps (gaps that this role's curriculum directly covers)
        bridged_skill_gaps = []
        for gap in skill_gaps:
            gap_clean = gap.lower()
            # Check against role technologies, concepts, and topics
            is_bridged = False
            for tech in role_data["core_technologies"]:
                if gap_clean in tech["name"].lower() or tech["name"].lower() in gap_clean:
                    is_bridged = True
                    break
            if not is_bridged:
                for top in role_data["technical_topics"]:
                    if any(gap_clean in s.lower() or s.lower() in gap_clean for s in top["skills"]):
                        is_bridged = True
                        break
            if is_bridged and gap not in bridged_skill_gaps:
                bridged_skill_gaps.append(gap)

        # 2. Identify leveraged skills (skills the student already has that give them an edge)
        leveraged_skills = []
        for sk in existing_skills:
            sk_clean = sk.lower()
            is_leveraged = False
            for tech in role_data["core_technologies"]:
                if sk_clean in tech["name"].lower() or tech["name"].lower() in sk_clean:
                    is_leveraged = True
                    break
            if not is_leveraged:
                for top in role_data["technical_topics"]:
                    if any(sk_clean in s.lower() or s.lower() in sk_clean for s in top["skills"]):
                        is_leveraged = True
                        break
            if is_leveraged and sk not in leveraged_skills:
                leveraged_skills.append(sk)

        # 3. Calculate Role Alignment Score
        total_core_techs = len(role_data["core_technologies"])
        matched_tech_count = len(leveraged_skills)
        base_pct = int(min(95, max(35, (matched_tech_count / max(1, total_core_techs)) * 70 + 30)))

        # Adjust for skill gaps
        if len(bridged_skill_gaps) > 3:
            alignment_score = max(40, base_pct - 10)
        elif len(leveraged_skills) >= 4:
            alignment_score = min(95, base_pct + 12)
        else:
            alignment_score = base_pct

        # 4. Formulate Personalized Guidance
        guidance_notes = []
        if leveraged_skills:
            guidance_notes.append(
                f"Your existing background in {', '.join(leveraged_skills[:3])} gives you a strong launchpad for this {canonical_role} path."
            )
        if bridged_skill_gaps:
            guidance_notes.append(
                f"This targeted curriculum will bridge {len(bridged_skill_gaps)} of your identified skill gaps ({', '.join(bridged_skill_gaps[:3])})."
            )
        else:
            guidance_notes.append(
                f"This curriculum focuses on sharpening core interview-tested competencies for {canonical_role}."
            )

        guidance_notes.append(
            f"Tailored for {company} campus placement standards."
        )
        personalized_guidance = " ".join(guidance_notes)

        # 5. Personalize technical topics with gap/strength badges
        personalized_topics = []
        for t in role_data["technical_topics"]:
            topic_copy = dict(t)
            topic_skills = [s.lower() for s in topic_copy.get("skills", [])]
            
            # Check gap connection
            connected_gaps = [g for g in skill_gaps if any(g.lower() in ts or ts in g.lower() for ts in topic_skills)]
            connected_strengths = [s for s in existing_skills if any(s.lower() in ts or ts in s.lower() for ts in topic_skills)]

            topic_copy["connected_gaps"] = connected_gaps
            topic_copy["connected_strengths"] = connected_strengths
            topic_copy["is_priority"] = bool(connected_gaps) or (t.get("importance") == "High")
            personalized_topics.append(topic_copy)

        # 6. Personalize coding questions
        personalized_questions = []
        for q in role_data["coding_questions"]:
            q_copy = dict(q)
            q_skills = [s.lower() for s in q_copy.get("skills_targeted", [])]
            q_gaps = [g for g in skill_gaps if any(g.lower() in qs or qs in g.lower() for qs in q_skills)]
            q_copy["targets_gap"] = q_gaps[0] if q_gaps else None
            personalized_questions.append(q_copy)

        # 7. Personalize 6-week roadmap
        personalized_roadmap = []
        for w in role_data["roadmap"]:
            w_copy = dict(w)
            w_topics_text = " ".join(w_copy.get("topics", [])).lower()
            w_gaps = [g for g in skill_gaps if g.lower() in w_topics_text]
            w_strengths = [s for s in existing_skills if s.lower() in w_topics_text]
            w_copy["bridged_gaps"] = w_gaps
            w_copy["leveraged_skills"] = w_strengths
            personalized_roadmap.append(w_copy)

        # Count total roadmap tasks
        total_tasks = 0
        for w in personalized_roadmap:
            total_tasks += len(w.get("topics", [])) + len(w.get("coding_practice", [])) + len(w.get("mini_projects", [])) + len(w.get("interview_questions", []))

        result_payload = {
            "success": True,
            "target_role": canonical_role,
            "role_title": role_data["title"],
            "tagline": role_data["tagline"],
            "icon": role_data["icon"],
            "color_class": role_data["color_class"],
            "company_name": company,
            "alignment_score": alignment_score,
            "leveraged_skills": leveraged_skills,
            "bridged_skill_gaps": bridged_skill_gaps,
            "personalized_guidance": personalized_guidance,
            "core_technologies": role_data["core_technologies"],
            "important_concepts": role_data["important_concepts"],
            "technical_topics": personalized_topics,
            "coding_questions": personalized_questions,
            "roadmap": personalized_roadmap,
            "total_roadmap_tasks": total_tasks,
            "available_roles": SUPPORTED_ROLES
        }

        return result_payload


role_prep_agent = RolePreparationAgent()

