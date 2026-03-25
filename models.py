from pydantic import BaseModel
from typing import Optional, List


class AnswerSubmission(BaseModel):
    student_id: int
    topic: str
    question: str
    student_answer: str
    correct_answer: str
    time_taken: float


class StudentCreate(BaseModel):
    name: str
    email: str
    password: str
    class_name: str = "General"


class TeacherCreate(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str
    role: str


class AssignmentCreate(BaseModel):
    teacher_id: int
    student_ids: List[int]
    title: str
    topic: str
    difficulty: str = "medium"
    num_questions: int = 1
    class_name: str = "General"
    deadline: Optional[str] = None


class AssignmentUpdate(BaseModel):
    title: Optional[str] = None
    question: Optional[str] = None
    correct_answer: Optional[str] = None
    hint: Optional[str] = None


class AssignmentComplete(BaseModel):
    student_answer: str
    time_taken: float
    