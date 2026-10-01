import io
import pandas as pd
from typing import List
from fastapi import FastAPI, UploadFile, File, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship

# --- 1. DATABASE SETUP ---
DATABASE_URL = "sqlite:///./portal.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- 2. DATABASE MODELS ---
class StudentDB(Base):
    __tablename__ = "students"
    admission_number = Column(String, primary_key=True, index=True)
    full_name = Column(String)
    course = Column(String)
    password = Column(String)
    total_fees = Column(Float, default=45000.0)
    fee_balance = Column(Float, default=12500.0)
    results = relationship("ResultDB", back_populates="student")

class ResultDB(Base):
    __tablename__ = "results"
    id = Column(Integer, primary_key=True, index=True)
    admission_number = Column(String, ForeignKey("students.admission_number"))
    unit_code = Column(String)
    unit_name = Column(String)
    cat_score = Column(Float)
    exam_score = Column(Float)
    total_score = Column(Float)
    grade = Column(String)
    is_retake = Column(Boolean)
    student = relationship("StudentDB", back_populates="results")

Base.metadata.create_all(bind=engine)

# --- 3. FASTAPI APP ---
app = FastAPI(title="Student Portal API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Seed default student if missing
@app.on_event("startup")
def seed_data():
    db = SessionLocal()
    if not db.query(StudentDB).filter(StudentDB.admission_number == "S12/00101/24").first():
        sample_student = StudentDB(
            admission_number="S12/00101/24",
            full_name="Jane Doe",
            course="BSc. Information Technology",
            password="password123",
            total_fees=45000.0,
            fee_balance=12500.0
        )
        db.add(sample_student)
        db.commit()

        sample_results = [
            ResultDB(admission_number="S12/00101/24", unit_code="BIT 1101", unit_name="Introduction to Programming", cat_score=24, exam_score=52, total_score=76, grade="A", is_retake=False),
            ResultDB(admission_number="S12/00101/24", unit_code="BIT 1102", unit_name="Database Management Systems", cat_score=18, exam_score=45, total_score=63, grade="B", is_retake=False),
            ResultDB(admission_number="S12/00101/24", unit_code="BIT 1103", unit_name="Discrete Mathematics", cat_score=12, exam_score=22, total_score=34, grade="E", is_retake=True),
        ]
        db.add_all(sample_results)
        db.commit()
    db.close()

class LoginRequest(BaseModel):
    admission_number: str
    password: str

@app.post("/api/student/login")
def student_login(credentials: LoginRequest, db: Session = Depends(get_db)):
    adm = credentials.admission_number.strip()
    student = db.query(StudentDB).filter(StudentDB.admission_number == adm).first()
    
    if not student or student.password != credentials.password:
        raise HTTPException(status_code=401, detail="Invalid Admission Number or Password")
    
    results = db.query(ResultDB).filter(ResultDB.admission_number == adm).all()

    return {
        "admission_number": student.admission_number,
        "full_name": student.full_name,
        "course": student.course,
        "fee_structure_total": student.total_fees,
        "fee_balance": student.fee_balance,
        "results": [
            {
                "unit_code": r.unit_code,
                "unit_name": r.unit_name,
                "cat_score": r.cat_score,
                "exam_score": r.exam_score,
                "total_score": r.total_score,
                "grade": r.grade,
                "is_retake": r.is_retake
            } for r in results
        ]
    }

# --- 4. EXCEL BULK UPLOAD ENDPOINT ---
def calculate_grade(total: float):
    if total >= 70: return "A", False
    if total >= 60: return "B", False
    if total >= 50: return "C", False
    if total >= 40: return "D", False
    return "E", True

@app.post("/api/admin/upload-results")
async def upload_results(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Only Excel files (.xlsx, .xls) are allowed.")

    contents = await file.read()
    df = pd.read_excel(io.BytesIO(contents))

    required_cols = {'admission_number', 'unit_code', 'unit_name', 'cat_score', 'exam_score'}
    if not required_cols.issubset(set(df.columns)):
        raise HTTPException(status_code=400, detail=f"Excel missing required columns: {required_cols}")

    processed_count = 0
    for _, row in df.iterrows():
        adm = str(row['admission_number']).strip()
        cat = float(row['cat_score'])
        exam = float(row['exam_score'])
        total = cat + exam
        grade, is_retake = calculate_grade(total)

        # Ensure student exists
        student = db.query(StudentDB).filter(StudentDB.admission_number == adm).first()
        if not student:
            student = StudentDB(admission_number=adm, full_name="New Student", course="Unassigned", password="password123")
            db.add(student)
            db.commit()

        # Add or update result
        new_result = ResultDB(
            admission_number=adm,
            unit_code=str(row['unit_code']),
            unit_name=str(row['unit_name']),
            cat_score=cat,
            exam_score=exam,
            total_score=total,
            grade=grade,
            is_retake=is_retake
        )
        db.add(new_result)
        processed_count += 1

    db.commit()
    return {"status": "success", "message": f"Successfully processed {processed_count} result records."}