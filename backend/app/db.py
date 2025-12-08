from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Voor nu: simpele SQLite file. Later kun je de URL vervangen door PostgreSQL.
SQLALCHEMY_DATABASE_URL = "sqlite:///./app.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},  # nodig voor SQLite + FastAPI
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
