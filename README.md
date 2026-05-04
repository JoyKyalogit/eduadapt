# EduAdapt

EduAdapt is a small **AI-assisted learning platform**: teachers and students sign up, complete assignments and practice, and get **Groq-powered** question generation, grading, and feedback. A **FastAPI** backend stores data in **PostgreSQL** and can serve the static UI from the `Frontend/` folder at `/`.

## Stack

| Layer | Technology |
|--------|------------|
| API | [FastAPI](https://fastapi.tiangolo.com/), [Uvicorn](https://www.uvicorn.org/) |
| Database | [PostgreSQL](https://www.postgresql.org/) via [asyncpg](https://magicstack.github.io/asyncpg/) |
| AI | [Groq](https://groq.com/) API (`llama-3.1-8b-instant` in `ai_service.py`) |
| Config | [python-dotenv](https://pypi.org/project/python-dotenv/) |

## Features (high level)

- Student and teacher accounts (hashed passwords).
- AI-generated and manual assignments; submissions graded with feedback.
- Practice sessions and stored quiz results.
- Teacher analytics (e.g. struggling students, topics, improvement trends).

Interactive API documentation is available at **`/docs`** when the server is running.

## Prerequisites

- Python **3.10+** (recommended)
- A **PostgreSQL** instance you can reach with SSL (`ssl=require` in code).
- A **Groq API key** from the [Groq Console](https://console.groq.com/).

## Local setup

```bash
git clone https://github.com/JoyKyalogit/eduadapt.git
cd eduadapt
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
```

Create a `.env` file in the project root (do not commit secrets). You can use **either** a single URL **or** discrete variables.

**Option A — URL (matches Render Blueprint):**

```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DATABASE
GROQ_API_KEY=your_groq_api_key
```

**Option B — discrete variables:**

```env
DB_HOST=your_host
DB_PORT=5432
DB_USER=your_user
DB_PASSWORD=your_password
DB_NAME=your_database
GROQ_API_KEY=your_groq_api_key
```

Start the API:

```bash
uvicorn main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) (or [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) for Swagger). If `Frontend/index.html` exists, `/` serves that UI.

## Deploy on Render

This repo includes **`render.yaml`** ([Render Blueprint](https://render.com/docs/blueprint-spec)):

- **PostgreSQL:** `eduadapt-db`
- **Web service:** `eduadapt-api` — `pip install -r requirements.txt`, then `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **`DATABASE_URL`** is wired from the database **`connectionString`**
- **`GROQ_API_KEY`** is marked `sync: false`; Render prompts you on first apply

**New → Blueprint** in the [Render Dashboard](https://dashboard.render.com), connect this repository, apply the blueprint, and set **`GROQ_API_KEY`** when asked.

> **Free Postgres limit:** Render allows only **one active free-tier PostgreSQL** per workspace. If blueprint database creation fails with that message, remove an unused free database or use a paid instance, then sync again.

## Project layout

| Path | Role |
|------|------|
| `main.py` | FastAPI routes and app lifespan |
| `database.py` | Connection pool, schema creation, migrations |
| `models.py` | Pydantic request/response models |
| `ai_service.py` | Groq: questions, grading, feedback |
| `analytics.py` | Teacher-side analytics helpers |
| `Frontend/` | Static frontend (optional), mounted when present |
| `Procfile` | `web: uvicorn main:app --host 0.0.0.0 --port $PORT` |
| `render.yaml` | Render Blueprint (optional IaC) |

## License

No license file is included in this repository yet; add one if you intend to open-source under specific terms.
