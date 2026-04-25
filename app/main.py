# app/main.py
from dotenv import load_dotenv
import os
from pathlib import Path


load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routes import webhook
from app.services.db_service import init_db

port = int(os.environ.get("PORT", 8000))


app = FastAPI()

images_dir = Path("app/images")
if images_dir.exists():
    app.mount("/images", StaticFiles(directory=images_dir), name="images")


@app.on_event("startup")
def startup_event():
    init_db()


app.include_router(webhook.router)

@app.get("/")
def home():
    return {"message": "Backend running 🚀"}
