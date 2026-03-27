from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import List, Optional
import asyncio
import bcrypt
import hashlib

from models import (AnswerSubmission, StudentCreate, TeacherCreate,
                    LoginRequest, AssignmentCreate, AssignmentUpdate, AssignmentComplete)
from database import db, create_tables
from ai_service import generate_feedback, generate_question, generate_questions_batch, grade_answer
from analytics import (get_struggling_students, get_hardest_topic,
                        get_student_report, get_most_improved_students)


def _prepare(password: str) -> bytes:
    return hashlib.sha256(password.encode("utf-8")).hexdigest().encode("utf-8")

def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(_prepare(plain), hashed.encode("utf-8"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    await create_tables()
    yield
    await db.close()

app = FastAPI(title="EduAdapt API", version="3.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

import os
if os.path.exists("Frontend"):
    app.mount("/static", StaticFiles(directory="Frontend"), name="static")

@app.get("/")
async def serve_frontend():
    if os.path.exists("Frontend/index.html"):
        return FileResponse("Frontend/index.html")
    return {"message": "EduAdapt API running"}


# ── STUDENTS ─────────────────────────────────────────────────────────────────
@app.post("/students")
async def create_student(data: StudentCreate):
    if not data.password or len(data.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters.")
    try:
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO students (name, email, password_hash, class_name)
                VALUES ($1, $2, $3, $4) RETURNING id, name, email, class_name, joined_at
            """, data.name, data.email, hash_password(data.password), data.class_name)
        return dict(row)
    except Exception as e:
        if 'unique' in str(e).lower():
            raise HTTPException(400, "An account with this email already exists. Please sign in.")
        raise HTTPException(400, str(e))


@app.get("/students")
async def get_all_students():
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name, email, class_name, joined_at FROM students ORDER BY class_name, name")
    return [dict(r) for r in rows]


@app.get("/students/{student_id}")
async def get_student(student_id: int):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, name, email, class_name, joined_at FROM students WHERE id = $1", student_id)
    if not row:
        raise HTTPException(404, "Student not found")
    return dict(row)


@app.get("/classes")
async def get_classes():
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT class_name FROM students ORDER BY class_name")
    return [r["class_name"] for r in rows]


@app.get("/classes/{class_name}/students")
async def get_class_students(class_name: str):
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, email, class_name, joined_at FROM students WHERE class_name = $1 ORDER BY name", class_name)
    return [dict(r) for r in rows]


# ── TEACHERS ─────────────────────────────────────────────────────────────
@app.post("/teachers")
async def create_teacher(data: TeacherCreate):
    if not data.password or len(data.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters.")
    try:
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO teachers (name, email, password_hash)
                VALUES ($1, $2, $3) RETURNING id, name, email, created_at
            """, data.name, data.email, hash_password(data.password))
        return dict(row)
    except Exception as e:
        if 'unique' in str(e).lower():
            raise HTTPException(400, "An account with this email already exists. Please sign in.")
        raise HTTPException(400, str(e))


@app.get("/teachers/{teacher_id}")
async def get_teacher(teacher_id: int):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, name, email, created_at FROM teachers WHERE id = $1", teacher_id)
    if not row:
        raise HTTPException(404, "Teacher not found")
    return dict(row)


# ── LOGIN ─────────────────────────────────────────────────────────────────────
@app.post("/login")
async def login(data: LoginRequest):
    email = data.email.strip().lower()
    table = "teachers" if data.role == "teacher" else "students"
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(f"SELECT * FROM {table} WHERE LOWER(email) = $1", email)
    if not row:
        other_table = "students" if data.role == "teacher" else "teachers"
        async with db.pool.acquire() as conn:
            other = await conn.fetchrow(f"SELECT id FROM {other_table} WHERE LOWER(email) = $1", email)
        if other:
            other_role = "student" if data.role == "teacher" else "teacher"
            raise HTTPException(401, f"This email is registered as a {other_role}, not a {data.role}.")
        raise HTTPException(401, "Invalid email or password.")
    if row["password_hash"] and not verify_password(data.password, row["password_hash"]):
        raise HTTPException(401, "Invalid email or password.")
    return {"id": row["id"], "name": row["name"], "email": row["email"], "role": data.role}


# ── SUBMIT ANSWER (practice only) ────────────────────────────────────────────
@app.post("/submit-answer")
async def submit_answer(data: AnswerSubmission):
    grading = await grade_answer(data.topic, data.question, data.student_answer, data.correct_answer)
    is_correct = grading["correct"]
    feedback = await generate_feedback(data.topic, data.question,
                                       data.student_answer, data.correct_answer, is_correct)
    try:
        async with db.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO quiz_results
                    (student_id, topic, question, student_answer, correct_answer, is_correct, time_taken, ai_feedback)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            """, data.student_id, data.topic, data.question, data.student_answer,
                data.correct_answer, is_correct, data.time_taken, feedback)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"correct": is_correct, "ai_feedback": feedback}


# ── SAVE PRACTICE SESSION ─────────────────────────────────────────────────────
class PracticeSessionSave(BaseModel):
    student_id: int
    topic: str
    difficulty: str
    total_questions: int
    correct_count: int

@app.post("/practice-results")
async def save_practice_result(data: PracticeSessionSave):
    score_pct = round(data.correct_count / data.total_questions * 100, 1) if data.total_questions > 0 else 0
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO practice_results (student_id, topic, difficulty, total_questions, correct_count, score_pct)
            VALUES ($1,$2,$3,$4,$5,$6) RETURNING id, topic, total_questions, correct_count, score_pct, taken_at
        """, data.student_id, data.topic, data.difficulty, data.total_questions, data.correct_count, score_pct)
    return dict(row)


@app.get("/practice-results/{student_id}")
async def get_practice_results(student_id: int):
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, topic, difficulty, total_questions, correct_count, score_pct, taken_at
            FROM practice_results WHERE student_id = $1
            ORDER BY taken_at DESC
        """, student_id)
    return [dict(r) for r in rows]


# ── GENERATE QUESTION ─────────────────────────────────────────────────────────
class GenerateQuestionRequest(BaseModel):
    topic: str
    difficulty: str = "medium"
    exclude: List[str] = []

@app.get("/generate-question")
async def get_generated_question(topic: str, difficulty: str = "medium", exclude: str = None):
    import json as _json
    try:
        excl = _json.loads(exclude) if exclude else []
    except Exception:
        excl = []
    result = await generate_question(topic, difficulty, exclude=excl)
    return result or {"question": None, "correct_answer": None, "hint": None}

@app.post("/generate-question")
async def post_generated_question(data: GenerateQuestionRequest):
    """POST version — supports large exclude lists without URL length limits."""
    # Try up to 5 times total before giving up
    for attempt in range(5):
        result = await generate_question(data.topic, data.difficulty, exclude=data.exclude)
        if result and result.get("question") and result.get("correct_answer"):
            return result
        await asyncio.sleep(0.3)
    raise HTTPException(503, "Could not generate question after multiple attempts. Please try again.")


# ── PROGRESS (assignment-based only) ─────────────────────────────────────────
@app.get("/progress/{student_id}")
async def student_progress(student_id: int):
    """Returns performance grouped by assignment title, with per-topic summary."""
    async with db.pool.acquire() as conn:
        # Per-assignment scores
        asgn_rows = await conn.fetch("""
            SELECT REGEXP_REPLACE(a.title, ' \\(Q\\d+/\\d+\\)$', '') AS base_title,
                   a.topic,
                   COUNT(*) AS total_q,
                   SUM(CASE WHEN a.is_correct THEN 1 ELSE 0 END) AS correct_q,
                   ROUND(AVG(CASE WHEN a.is_correct THEN 1.0 ELSE 0.0 END)::numeric,2) AS pct,
                   ROUND(AVG(a.time_taken)::numeric,1) AS avg_time,
                   t.name AS teacher_name,
                   MAX(a.completed_at) AS submitted_at
            FROM assignments a
            JOIN teachers t ON t.id = a.teacher_id
            WHERE a.student_id = $1 AND a.status = 'completed'
            GROUP BY base_title, a.topic, t.name
            ORDER BY submitted_at DESC
        """, student_id)
        # Per-topic summary
        topic_rows = await conn.fetch("""
            SELECT a.topic,
                   COUNT(*) AS total_attempts,
                   SUM(CASE WHEN a.is_correct THEN 1 ELSE 0 END) AS correct_count,
                   ROUND(AVG(CASE WHEN a.is_correct THEN 1.0 ELSE 0.0 END)::numeric, 2) AS avg_score,
                   ROUND(AVG(a.time_taken)::numeric, 1) AS avg_time_seconds
            FROM assignments a
            WHERE a.student_id = $1 AND a.status = 'completed'
            GROUP BY a.topic ORDER BY a.topic
        """, student_id)
    if not asgn_rows:
        raise HTTPException(404, "No assignment data found")
    return {
        "student_id": student_id,
        "assignments": [dict(r) for r in asgn_rows],
        "topics": [dict(r) for r in topic_rows]
    }


# ── ANALYTICS — teacher-scoped, completed assignments only ───────────────────

@app.get("/analytics/by-assignment")
async def analytics_by_assignment(teacher_id: int, class_name: str = None):
    """Returns results grouped by assignment title → questions → students with answers."""
    import re as _re
    async with db.pool.acquire() as conn:
        q = """
            SELECT a.id, a.title, a.topic, a.difficulty,
                   a.question, a.correct_answer,
                   a.is_correct, a.student_answer, a.time_taken,
                   a.assigned_at, a.completed_at,
                   s.id AS student_id, s.name AS student_name, s.class_name
            FROM assignments a JOIN students s ON s.id = a.student_id
            WHERE a.teacher_id = $1 AND a.status = 'completed'
        """
        params = [teacher_id]
        if class_name:
            q += " AND s.class_name = $2"
            params.append(class_name)
        q += " ORDER BY a.assigned_at ASC, a.title, s.name"
        rows = await conn.fetch(q, *params)

    assignments = {}
    for r in rows:
        base = _re.sub(r' \(Q\d+/\d+\)$', '', r['title'])
        key = base + '||' + r['topic']
        if key not in assignments:
            assignments[key] = {
                'title': base, 'topic': r['topic'], 'difficulty': r['difficulty'],
                'assigned_at': r['assigned_at'].isoformat() if r['assigned_at'] else None,
                'questions': {}
            }
        qtext = r['question']
        if qtext not in assignments[key]['questions']:
            assignments[key]['questions'][qtext] = {
                'question': qtext,
                'correct_answer': r['correct_answer'],
                'students': []
            }
        assignments[key]['questions'][qtext]['students'].append({
            'student_id': r['student_id'], 'name': r['student_name'],
            'class_name': r['class_name'], 'student_answer': r['student_answer'],
            'is_correct': r['is_correct'],
            'time_taken': round(r['time_taken'], 1) if r['time_taken'] else None
        })

    result = []
    for asgn in assignments.values():
        questions = list(asgn['questions'].values())
        student_totals = {}
        for q_data in questions:
            for s in q_data['students']:
                sid = s['student_id']
                if sid not in student_totals:
                    student_totals[sid] = {'student_id': sid, 'name': s['name'], 'class_name': s['class_name'],
                                           'correct': 0, 'total': 0}
                student_totals[sid]['total'] += 1
                if s['is_correct']:
                    student_totals[sid]['correct'] += 1
        students_summary = [
            {**v, 'pct': round(v['correct']/v['total']*100) if v['total'] else 0}
            for v in student_totals.values()
        ]
        result.append({
            'title': asgn['title'], 'topic': asgn['topic'],
            'difficulty': asgn['difficulty'], 'assigned_at': asgn['assigned_at'],
            'students_summary': students_summary, 'questions': questions
        })
    return result


@app.get("/analytics/struggling")
async def struggling_students(teacher_id: int, threshold: float = 0.6, class_name: str = None):
    """Returns struggling students with the specific topics they struggle on."""
    async with db.pool.acquire() as conn:
        q = """
            SELECT s.id, s.name, s.class_name, a.topic,
                   COUNT(*) AS total_attempts,
                   SUM(CASE WHEN a.is_correct THEN 1 ELSE 0 END) AS correct_count,
                   ROUND(AVG(CASE WHEN a.is_correct THEN 1.0 ELSE 0.0 END)::numeric,2) AS avg_score
            FROM assignments a JOIN students s ON s.id = a.student_id
            WHERE a.teacher_id = $1 AND a.status = 'completed'
        """
        params = [teacher_id]
        if class_name:
            q += " AND s.class_name = $2"
            params.append(class_name)
        q += " GROUP BY s.id, s.name, s.class_name, a.topic HAVING AVG(CASE WHEN a.is_correct THEN 1.0 ELSE 0.0 END) < $" + str(len(params)+1) + " ORDER BY s.name, avg_score ASC"
        params.append(threshold)
        rows = await conn.fetch(q, *params)
    # Group by student, collect struggling topics
    students = {}
    for r in rows:
        sid = r['id']
        if sid not in students:
            students[sid] = {'name': r['name'], 'class_name': r['class_name'], 'topics': []}
        students[sid]['topics'].append({
            'topic': r['topic'],
            'correct': int(r['correct_count']),
            'total': int(r['total_attempts']),
            'pct': round(float(r['avg_score'])*100)
        })
    return {"threshold": threshold, "count": len(students),
            "students": list(students.values())}


@app.get("/analytics/hardest-topic")
async def hardest_topic(teacher_id: int, class_name: str = None):
    """Returns all topics ranked by avg score ascending (hardest first)."""
    async with db.pool.acquire() as conn:
        if class_name:
            rows = await conn.fetch("""
                SELECT a.topic,
                       ROUND(AVG(CASE WHEN a.is_correct THEN 1.0 ELSE 0.0 END)::numeric,2) AS avg_score,
                       COUNT(*) AS total_attempts,
                       SUM(CASE WHEN a.is_correct THEN 1 ELSE 0 END) AS correct_count
                FROM assignments a JOIN students s ON s.id = a.student_id
                WHERE a.teacher_id = $1 AND a.status = 'completed' AND s.class_name = $2
                GROUP BY a.topic ORDER BY avg_score ASC
            """, teacher_id, class_name)
        else:
            rows = await conn.fetch("""
                SELECT topic,
                       ROUND(AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END)::numeric,2) AS avg_score,
                       COUNT(*) AS total_attempts,
                       SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) AS correct_count
                FROM assignments WHERE teacher_id = $1 AND status = 'completed'
                GROUP BY topic ORDER BY avg_score ASC
            """, teacher_id)
    if not rows:
        return {"message": "No submitted assignments yet"}
    return [dict(r) for r in rows]


@app.get("/analytics/most-improved")
async def most_improved(teacher_id: int, class_name: str = None):
    """Most improved per topic — compares early vs recent attempts per student per topic."""
    async with db.pool.acquire() as conn:
        q = """
            WITH ranked AS (
                SELECT a.student_id, a.topic, a.is_correct, a.completed_at,
                       ROW_NUMBER() OVER (PARTITION BY a.student_id, a.topic ORDER BY a.completed_at ASC) AS rn_asc,
                       ROW_NUMBER() OVER (PARTITION BY a.student_id, a.topic ORDER BY a.completed_at DESC) AS rn_desc,
                       COUNT(*) OVER (PARTITION BY a.student_id, a.topic) AS total
                FROM assignments a JOIN students s ON s.id = a.student_id
                WHERE a.teacher_id = $1 AND a.status = 'completed'
        """
        params = [teacher_id]
        if class_name:
            q += " AND s.class_name = $2"
            params.append(class_name)
        q += """
            ),
            early AS (SELECT student_id, topic, AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) AS early_avg
                      FROM ranked WHERE total >= 2 AND rn_asc <= GREATEST(total/2,1) GROUP BY student_id, topic),
            recent AS (SELECT student_id, topic, AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) AS recent_avg
                       FROM ranked WHERE total >= 2 AND rn_desc <= GREATEST(total/2,1) GROUP BY student_id, topic)
            SELECT s.name, s.class_name, e.topic,
                   ROUND(e.early_avg::numeric,2) AS early_avg,
                   ROUND(r.recent_avg::numeric,2) AS recent_avg,
                   ROUND((r.recent_avg - e.early_avg)::numeric,2) AS improvement
            FROM early e JOIN recent r ON e.student_id=r.student_id AND e.topic=r.topic
            JOIN students s ON s.id=e.student_id
            WHERE (r.recent_avg - e.early_avg) > 0
            ORDER BY improvement DESC
        """
        rows = await conn.fetch(q, *params)
    return [dict(r) for r in rows]


# ── ASSIGNMENTS ───────────────────────────────────────────────────────────────
@app.post("/assignments")
async def create_assignment(data: AssignmentCreate):
    if not data.student_ids:
        raise HTTPException(400, "Please select at least one student.")
    num_q = max(1, min(data.num_questions, 20))
    num_students = len(data.student_ids)

    from datetime import datetime
    deadline = None
    if getattr(data, 'deadline', None):
        try:
            deadline = datetime.fromisoformat(data.deadline)
        except Exception:
            deadline = None

    # Fetch existing questions for this topic to avoid repeating past assignments
    async with db.pool.acquire() as conn:
        existing_rows = await conn.fetch(
            "SELECT DISTINCT question FROM assignments WHERE topic = $1", data.topic
        )
    existing_questions = [r["question"] for r in existing_rows]

    # Generate num_q questions ONCE — every student gets the exact same set
    try:
        shared_questions = await generate_questions_batch(
            data.topic, data.difficulty, num_q, existing=existing_questions
        )
    except Exception as e:
        raise HTTPException(500, f"Question generation failed: {e}")

    if not shared_questions:
        raise HTTPException(503, "Could not generate questions. Please try again.")

    # Filter out any invalid questions
    shared_questions = [q for q in shared_questions if q and q.get("question") and q.get("correct_answer")]
    if not shared_questions:
        raise HTTPException(503, "Generated questions were invalid. Please try again.")

    created = []
    try:
        async with db.pool.acquire() as conn:
            for student_id in data.student_ids:
                for q_num, question_data in enumerate(shared_questions):
                    label = f" (Q{q_num+1}/{num_q})" if num_q > 1 else ""
                    row = await conn.fetchrow("""
                        INSERT INTO assignments
                            (teacher_id, student_id, title, topic, difficulty,
                             question, correct_answer, hint, class_name, status, deadline)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'pending',$10)
                        RETURNING id, student_id, title, topic, status
                    """, data.teacher_id, student_id, data.title + label,
                        data.topic, data.difficulty,
                        question_data["question"], question_data.get("correct_answer", ""),
                        question_data.get("hint", ""), data.class_name, deadline)
                    created.append(dict(row))
        return {"assigned": num_students, "total_questions": len(created), "assignments": created}
    except Exception as e:
        raise HTTPException(500, str(e))


class ManualAssignmentCreate(BaseModel):
    teacher_id: int
    student_ids: List[int]
    title: str
    topic: str
    difficulty: str = "medium"
    class_name: str = "General"
    questions: List[dict]
    deadline: Optional[str] = None


@app.post("/assignments/manual")
async def create_manual_assignment(data: ManualAssignmentCreate):
    if not data.student_ids:
        raise HTTPException(400, "Please select at least one student.")
    if not data.questions:
        raise HTTPException(400, "Please provide at least one question.")
    from datetime import datetime
    deadline = None
    if data.deadline:
        try:
            deadline = datetime.fromisoformat(data.deadline)
        except Exception:
            deadline = None
    created = []
    try:
        async with db.pool.acquire() as conn:
            for student_id in data.student_ids:
                for i, q in enumerate(data.questions):
                    label = f" (Q{i+1}/{len(data.questions)})" if len(data.questions) > 1 else ""
                    row = await conn.fetchrow("""
                        INSERT INTO assignments
                            (teacher_id, student_id, title, topic, difficulty,
                             question, correct_answer, hint, class_name, status, deadline)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'pending',$10)
                        RETURNING id, student_id, title, topic, status
                    """, data.teacher_id, student_id, data.title + label,
                        data.topic, data.difficulty,
                        q["question"], q["correct_answer"],
                        q.get("hint", ""), data.class_name, deadline)
                    created.append(dict(row))
        return {"assigned": len(data.student_ids), "total_questions": len(created), "assignments": created}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/assignments/student/{student_id}")
async def get_student_assignments(student_id: int):
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT a.id, a.title, a.topic, a.difficulty, a.question,
                   a.status, a.is_correct, a.ai_feedback, a.student_answer,
                   a.class_name, a.assigned_at, a.completed_at, a.deadline,
                   t.name AS teacher_name
            FROM assignments a
            JOIN teachers t ON t.id = a.teacher_id
            WHERE a.student_id = $1
            ORDER BY a.assigned_at DESC
        """, student_id)
    return [dict(r) for r in rows]


@app.get("/assignments/teacher/{teacher_id}")
async def get_teacher_assignments(teacher_id: int, class_name: str = None):
    async with db.pool.acquire() as conn:
        if class_name:
            rows = await conn.fetch("""
                SELECT a.id, a.title, a.topic, a.difficulty, a.question,
                       a.correct_answer, a.class_name, a.deadline,
                       a.status, a.is_correct, a.student_answer, a.ai_feedback,
                       a.assigned_at, a.completed_at,
                       s.name AS student_name, s.email AS student_email, s.id AS student_id
                FROM assignments a JOIN students s ON s.id = a.student_id
                WHERE a.teacher_id = $1 AND a.class_name = $2
                ORDER BY s.name, a.title, a.assigned_at
            """, teacher_id, class_name)
        else:
            rows = await conn.fetch("""
                SELECT a.id, a.title, a.topic, a.difficulty, a.question,
                       a.correct_answer, a.class_name, a.deadline,
                       a.status, a.is_correct, a.student_answer, a.ai_feedback,
                       a.assigned_at, a.completed_at,
                       s.name AS student_name, s.email AS student_email, s.id AS student_id
                FROM assignments a JOIN students s ON s.id = a.student_id
                WHERE a.teacher_id = $1
                ORDER BY a.class_name, s.name, a.title, a.assigned_at
            """, teacher_id)
    return [dict(r) for r in rows]


@app.get("/assignments/teacher/{teacher_id}/by-title")
async def get_teacher_assignments_by_title(teacher_id: int, class_name: str = None):
    """Return assignments grouped by title (one assignment = all its questions)."""
    async with db.pool.acquire() as conn:
        if class_name:
            rows = await conn.fetch("""
                SELECT a.id, a.title, a.topic, a.question, a.correct_answer,
                       a.difficulty, a.class_name, a.status, a.assigned_at,
                       a.student_answer, a.is_correct,
                       s.name AS student_name, s.email AS student_email
                FROM assignments a JOIN students s ON s.id = a.student_id
                WHERE a.teacher_id = $1 AND a.class_name = $2
                ORDER BY a.title, a.assigned_at
            """, teacher_id, class_name)
        else:
            rows = await conn.fetch("""
                SELECT a.id, a.title, a.topic, a.question, a.correct_answer,
                       a.difficulty, a.class_name, a.status, a.assigned_at,
                       a.student_answer, a.is_correct,
                       s.name AS student_name, s.email AS student_email
                FROM assignments a JOIN students s ON s.id = a.student_id
                WHERE a.teacher_id = $1
                ORDER BY a.title, a.assigned_at
            """, teacher_id)
    return [dict(r) for r in rows]


@app.patch("/assignments/{assignment_id}/edit")
async def edit_assignment(assignment_id: int, data: AssignmentUpdate):
    async with db.pool.acquire() as conn:
        assignment = await conn.fetchrow("SELECT * FROM assignments WHERE id = $1", assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    if assignment["status"] == "completed":
        raise HTTPException(400, "Cannot edit a completed assignment")
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE assignments SET
                title=COALESCE($1,title), question=COALESCE($2,question),
                correct_answer=COALESCE($3,correct_answer), hint=COALESCE($4,hint)
            WHERE id=$5
            RETURNING id, title, topic, difficulty, question, correct_answer, hint, status
        """, data.title, data.question, data.correct_answer, data.hint, assignment_id)
    return dict(row)


@app.delete("/assignments/bulk")
async def delete_assignment_by_title(teacher_id: int, title: str):
    """Delete all questions under an assignment title for all students."""
    base = title.split(" (Q")[0]
    async with db.pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM assignments WHERE teacher_id = $1 AND (title = $2 OR title LIKE $3)",
            teacher_id, base, base + " (Q%"
        )
    return {"message": "Assignment deleted"}


@app.delete("/assignments/{assignment_id}")
async def delete_single_assignment(assignment_id: int):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM assignments WHERE id = $1", assignment_id)
    if not row:
        raise HTTPException(404, "Assignment not found")
    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM assignments WHERE id = $1", assignment_id)
    return {"message": "Assignment deleted"}


@app.patch("/assignments/{assignment_id}/complete")
async def complete_assignment(assignment_id: int, data: AssignmentComplete):
    async with db.pool.acquire() as conn:
        assignment = await conn.fetchrow("SELECT * FROM assignments WHERE id = $1", assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    if assignment["status"] == "completed":
        raise HTTPException(400, "Assignment already completed")
    grading = await grade_answer(assignment["topic"], assignment["question"],
                                 data.student_answer, assignment["correct_answer"])
    is_correct = grading["correct"]
    feedback = await generate_feedback(assignment["topic"], assignment["question"],
                                       data.student_answer, assignment["correct_answer"], is_correct)
    async with db.pool.acquire() as conn:
        await conn.execute("""
            UPDATE assignments SET student_answer=$1, is_correct=$2, ai_feedback=$3,
                time_taken=$4, status='completed', completed_at=CURRENT_TIMESTAMP
            WHERE id=$5
        """, data.student_answer, is_correct, feedback, data.time_taken, assignment_id)
    return {"correct": is_correct, "ai_feedback": feedback}


@app.get("/admin/reset-all")
async def reset_all(confirm: str = ""):
    if confirm != "YES":
        raise HTTPException(400, "Pass ?confirm=YES to confirm reset.")
    async with db.pool.acquire() as conn:
        await conn.execute("TRUNCATE assignments, quiz_results, performance_history, practice_results, students, teachers RESTART IDENTITY CASCADE;")
    return {"message": "All data cleared successfully."}