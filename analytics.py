from database import db


async def get_struggling_students(threshold: float, class_name: str = None):
    async with db.pool.acquire() as conn:
        if class_name:
            rows = await conn.fetch("""
                SELECT s.id, s.name, s.email, s.class_name,
                    ROUND(AVG(CASE WHEN q.is_correct THEN 1.0 ELSE 0.0 END)::numeric,2) AS avg_score,
                    COUNT(q.id) AS total_attempts
                FROM students s JOIN quiz_results q ON s.id = q.student_id
                WHERE s.class_name = $2
                GROUP BY s.id, s.name, s.email, s.class_name
                HAVING AVG(CASE WHEN q.is_correct THEN 1.0 ELSE 0.0 END) < $1
                ORDER BY avg_score ASC
            """, threshold, class_name)
        else:
            rows = await conn.fetch("""
                SELECT s.id, s.name, s.email, s.class_name,
                    ROUND(AVG(CASE WHEN q.is_correct THEN 1.0 ELSE 0.0 END)::numeric,2) AS avg_score,
                    COUNT(q.id) AS total_attempts
                FROM students s JOIN quiz_results q ON s.id = q.student_id
                GROUP BY s.id, s.name, s.email, s.class_name
                HAVING AVG(CASE WHEN q.is_correct THEN 1.0 ELSE 0.0 END) < $1
                ORDER BY avg_score ASC
            """, threshold)
    return [dict(r) for r in rows]


async def get_hardest_topic(class_name: str = None):
    async with db.pool.acquire() as conn:
        if class_name:
            row = await conn.fetchrow("""
                SELECT q.topic,
                    ROUND(AVG(CASE WHEN q.is_correct THEN 1.0 ELSE 0.0 END)::numeric,2) AS avg_score,
                    COUNT(*) AS total_attempts
                FROM quiz_results q JOIN students s ON s.id = q.student_id
                WHERE s.class_name = $1
                GROUP BY q.topic ORDER BY avg_score ASC LIMIT 1
            """, class_name)
        else:
            row = await conn.fetchrow("""
                SELECT topic,
                    ROUND(AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END)::numeric,2) AS avg_score,
                    COUNT(*) AS total_attempts
                FROM quiz_results GROUP BY topic ORDER BY avg_score ASC LIMIT 1
            """)
    return dict(row) if row else {"message": "No quiz data available yet"}


async def get_student_report(student_id: int):
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT topic, COUNT(*) AS total_attempts,
                SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) AS correct_count,
                ROUND(AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END)::numeric,2) AS avg_score,
                ROUND(AVG(time_taken)::numeric,2) AS avg_time_seconds
            FROM quiz_results WHERE student_id = $1
            GROUP BY topic ORDER BY avg_score ASC
        """, student_id)
    return [dict(r) for r in rows]


async def get_most_improved_students(class_name: str = None):
    async with db.pool.acquire() as conn:
        base = """
            WITH ranked AS (
                SELECT student_id, is_correct, created_at,
                    ROW_NUMBER() OVER (PARTITION BY student_id ORDER BY created_at ASC) AS rn_asc,
                    ROW_NUMBER() OVER (PARTITION BY student_id ORDER BY created_at DESC) AS rn_desc,
                    COUNT(*) OVER (PARTITION BY student_id) AS total
                FROM quiz_results {join} {where}
            ),
            early AS (
                SELECT student_id, AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) AS early_avg
                FROM ranked WHERE rn_asc <= GREATEST(total/2,1) GROUP BY student_id
            ),
            recent AS (
                SELECT student_id, AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) AS recent_avg
                FROM ranked WHERE rn_desc <= GREATEST(total/2,1) GROUP BY student_id
            )
            SELECT s.id, s.name, s.email, s.class_name,
                ROUND(e.early_avg::numeric,2) AS early_avg,
                ROUND(r.recent_avg::numeric,2) AS recent_avg,
                ROUND((r.recent_avg - e.early_avg)::numeric,2) AS improvement
            FROM early e JOIN recent r ON e.student_id=r.student_id
            JOIN students s ON s.id=e.student_id
            ORDER BY improvement DESC
        """
        if class_name:
            rows = await conn.fetch(
                base.format(join="JOIN students st ON st.id=quiz_results.student_id",
                            where="WHERE st.class_name=$1"), class_name)
        else:
            rows = await conn.fetch(base.format(join="", where=""))
    return [dict(r) for r in rows]