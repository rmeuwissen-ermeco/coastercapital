from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import Base, engine
from . import models
from .routers import manufacturers, parks, coasters, suggestions, debug, extract

# Tabellen aanmaken (SQLite) – nu mét alle modellen geladen
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="CoasterCapital API",
    version="0.1.0",
    description="Backend voor CoasterCapital – stap 1: manufacturers/parks/coasters + AI-suggesties.",
)


origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "message": "Backend draait"}


@app.get("/")
def root():
    return {"message": "CoasterCapital API – zie /health of /docs"}


app.include_router(manufacturers.router)
app.include_router(parks.router)
app.include_router(coasters.router)
app.include_router(suggestions.router)
app.include_router(debug.router)
app.include_router(extract.router)
