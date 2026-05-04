# EduAdapt

EduAdapt is an AI-powered learning system designed for classroom use. It supports the full learning loop: teachers create assignments, students answer questions, AI evaluates responses, and analytics show learning progress over time.

## Live Demo

- [EduAdapt on Render](https://eduadapt-api.onrender.com)

## What the system is about

EduAdapt helps schools move from one-time grading to continuous learning insights.

- **Teachers** can assign work by topic and difficulty, then monitor class performance.
- **Students** can complete assignments and self-practice with instant feedback.
- **AI** generates questions, grades answers, and explains results.
- **Analytics** surface struggling learners, difficult topics, and improvement trends.

The core idea is adaptive learning: use each answer to guide what happens next.

## How the system works

### 1) Account and role flow

Users join as either **teacher** or **student**. Authentication is role-aware, and passwords are stored as hashes.

### 2) Assignment flow

A teacher creates an assignment by selecting:

- topic
- difficulty
- class
- one or more students

Assignments can be:

- **AI-generated** (questions produced in batch)
- **Manual** (teacher-provided questions)

Each selected student gets assignment entries tracked with status (`pending` -> `completed`).

### 3) Submission and grading flow

When a student submits an answer, the system:

1. grades correctness with AI,
2. generates AI feedback,
3. stores student answer, score outcome, time taken, and feedback,
4. marks the assignment completed.

### 4) Practice flow

Students can request practice questions outside formal assignments. Practice sessions are saved separately, so teachers can distinguish class tasks from self-study.

### 5) Analytics flow

Teacher analytics aggregate completed assignment data to answer questions like:

- Which students are struggling?
- Which topics are hardest?
- Who is improving over time?

## Architecture overview

EduAdapt is a FastAPI backend with a modular structure:

- `main.py`: API routes and orchestration logic
- `database.py`: PostgreSQL connection pool, table creation, and migrations
- `ai_service.py`: Groq integration for generation, grading, feedback
- `models.py`: Pydantic schemas for request validation
- `analytics.py`: SQL aggregation logic for reports
- `Frontend/`: optional static UI served by FastAPI at `/`

## Data and infrastructure

- **Database**: PostgreSQL via `asyncpg`
- **AI provider**: Groq API
- **Config**: environment variables (`DATABASE_URL` or `DB_*`), plus `GROQ_API_KEY`
- **Runtime**: Uvicorn/FastAPI

## Tech stack

- Python
- FastAPI
- asyncpg
- Pydantic
- python-dotenv
- Groq API

## Run locally

```bash
git clone https://github.com/JoyKyalogit/eduadapt.git
cd eduadapt
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000/docs` to explore endpoints.

## Environment variables

Use either of these approaches:

### Option A: single connection URL

```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DATABASE
GROQ_API_KEY=your_groq_api_key
```

### Option B: individual database values

```env
DB_HOST=your_host
DB_PORT=5432
DB_USER=your_user
DB_PASSWORD=your_password
DB_NAME=your_database
GROQ_API_KEY=your_groq_api_key
```

## Deploy on Render

This repository includes `render.yaml` for Render Blueprint deployment.

It defines:

- Postgres service: `eduadapt-db`
- Web service: `eduadapt-api`
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- `DATABASE_URL` injected from Render Postgres `connectionString`
- `GROQ_API_KEY` prompted securely via `sync: false`

Deploy via Render Dashboard -> **New -> Blueprint** -> select this repo.

## Current status and notes

- The system is API-first and works with or without the static frontend.
- Tables are created automatically at startup if missing.
- Keep secrets out of Git commits (`.env` should remain local).

## License

No license file is included yet.
