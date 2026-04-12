# app/main.py
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from app.routes import webhook

app = FastAPI()

app.include_router(webhook.router)

@app.get("/")
def home():
    return {"message": "Backend running 🚀"}
