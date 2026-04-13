# app/main.py
from dotenv import load_dotenv
import os


load_dotenv()

from fastapi import FastAPI
from app.routes import webhook

port = int(os.environ.get("PORT", 8000))


app = FastAPI()

app.include_router(webhook.router)

@app.get("/")
def home():
    return {"message": "Backend running 🚀"}
