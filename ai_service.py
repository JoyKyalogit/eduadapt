import os
import asyncio
import json
import re
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

_MODEL = "llama-3.1-8b-instant"
_client = None

def _get_client():
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY environment variable is not set.")
        _client = Groq(api_key=api_key)
    return _client


def _call_groq(prompt: str, max_tokens: int = 512) -> str:
    response = _get_client().chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        timeout=20,
        max_tokens=max_tokens,
        temperature=0.95,
    )
    return response.choices[0].message.content.strip()


def _extract_json(raw: str, expect_array: bool = False):
    """Robustly extract JSON from model output, stripping fences and finding brackets."""
    s = re.sub(r'^```(?:json)?\s*', '', raw.strip())
    s = re.sub(r'\s*```$', '', s).strip()
    if expect_array:
        i, j = s.find('['), s.rfind(']')
        if i != -1 and j != -1:
            try:
                return json.loads(s[i:j+1])
            except Exception:
                pass
        # Try extracting individual objects
        objs = re.findall(r'\{[^{}]+\}', s, re.DOTALL)
        results = []
        for o in objs:
            try:
                results.append(json.loads(o))
            except Exception:
                pass
        return results if results else None
    else:
        i, j = s.find('{'), s.rfind('}')
        if i != -1 and j != -1:
            try:
                return json.loads(s[i:j+1])
            except Exception:
                pass
        return None


def _valid(q) -> bool:
    if not isinstance(q, dict): return False
    question = (q.get("question") or "").strip()
    answer = (q.get("correct_answer") or "").strip()
    if not question or not answer: return False
    if answer.upper() in ("N/A", "NA", "NONE", "NULL", "TBD", ""): return False
    if "explain a key concept" in question.lower(): return False
    return True


# ── GRADING ───────────────────────────────────────────────────────────────────
async def grade_answer(topic: str, question: str, student_answer: str, correct_answer: str) -> dict:
    prompt = (f'Grade this answer. Topic: {topic}\nQ: {question}\n'
              f'Correct: {correct_answer}\nStudent: {student_answer}\n'
              f'Reply ONLY with JSON: {{"correct":true,"reason":"why"}}')
    try:
        raw = await asyncio.to_thread(_call_groq, prompt, 120)
        r = _extract_json(raw) or {}
        return {"correct": bool(r.get("correct")), "reason": r.get("reason", "")}
    except Exception:
        return {"correct": student_answer.strip().lower() == correct_answer.strip().lower(), "reason": ""}


# ── FEEDBACk ──────────────────────────────────────────────────────────────────
async def generate_feedback(topic: str, question: str, student_answer: str,
                             correct_answer: str, is_correct: bool) -> str:
    if is_correct:
        prompt = (f'The student answered correctly. Topic: {topic}\nQ: {question}\n'
                  f'Their answer: {student_answer}\nCorrect: {correct_answer}\n'
                  f'Write 1-2 warm sentences confirming they are right and briefly why.')
    else:
        prompt = (f'The student answered incorrectly. Topic: {topic}\nQ: {question}\n'
                  f'Their answer: {student_answer}\nCorrect: {correct_answer}\n'
                  f'Write 2-3 kind sentences: acknowledge any partial credit, state the correct answer, explain briefly. No bullet points.')
    try:
        fb = await asyncio.to_thread(_call_groq, prompt, 180)
        return fb or f"The correct answer is: {correct_answer}"
    except Exception:
        return f"The correct answer is: {correct_answer}"


# ── SINGLE QUESTION ───────────────────────────────────────────────────────────
async def generate_question(topic: str, difficulty: str = "medium", exclude: list = None) -> dict | None:
    excl_clause = ""
    if exclude:
        sample = exclude[-6:]
        excl_clause = "\nAvoid these:\n" + "\n".join(f"- {q}" for q in sample)

    prompt = (f'Write one {difficulty} quiz question about "{topic}".{excl_clause}\n'
              f'JSON only, no extra text:\n'
              f'{{"question":"...","correct_answer":"...","hint":"..."}}')

    for _ in range(3):
        try:
            raw = await asyncio.to_thread(_call_groq, prompt, 256)
            q = _extract_json(raw)
            if _valid(q):
                return q
        except Exception:
            pass
        await asyncio.sleep(0.2)
    return None


# ── BATCH GENERATION ─────────────────────────────────────────────────────────
async def generate_questions_batch(topic: str, difficulty: str, count: int,
                                    existing: list = None) -> list:
    """
    Generate `count` unique questions in one call.
    All students get the same set — called once per assignment.
    """
    excl = (existing or [])[-10:]
    excl_clause = ""
    if excl:
        excl_clause = "\nDo NOT repeat:\n" + "\n".join(f"- {q}" for q in excl)

    prompt = (f'Write exactly {count} different {difficulty} quiz questions about "{topic}".\n'
              f'Each question must test a DIFFERENT concept.{excl_clause}\n'
              f'JSON array only, no other text:\n'
              f'[{{"question":"...","correct_answer":"...","hint":"..."}},...]')

    for attempt in range(3):
        try:
            raw = await asyncio.to_thread(_call_groq, prompt, min(2048, count * 220))
            items = _extract_json(raw, expect_array=True)
            if isinstance(items, list):
                seen = set(existing or [])
                valid = []
                for q in items:
                    if _valid(q) and q["question"] not in seen:
                        seen.add(q["question"])
                        valid.append(q)
                if len(valid) >= count:
                    return valid[:count]
                # Fill any gaps individually
                for _ in range(count - len(valid)):
                    q = await generate_question(topic, difficulty, exclude=list(seen))
                    if q and q.get("question") not in seen:
                        seen.add(q.get("question", ""))
                        valid.append(q)
                if valid:
                    return valid[:count]
        except Exception:
            pass
        await asyncio.sleep(0.3)

    # Full fallback — individual call
    seen = set(existing or [])
    questions = []
    tasks = [generate_question(topic, difficulty, exclude=list(seen)) for _ in range(count)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if r and not isinstance(r, Exception) and _valid(r):
            seen.add(r.get("question", ""))
            questions.append(r)
    return questions