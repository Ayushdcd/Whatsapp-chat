from fastapi import APIRouter, Request
from app.services.groq_service import generate_ai_reply

router = APIRouter()

@router.post("/webhook")
async def receive_message(request: Request):
    data = await request.json()

    try:
        message = data['messages'][0]['text']['body']
        mobile = data['messages'][0]['from']
    except Exception:
        return {"status": "ignored"}

    print(f"User ({mobile}): {message}")

    # 🔥 Call AI
    reply = generate_ai_reply(message)

    print(f"Bot: {reply}")

    return {
        "user": message,
        "reply": reply
    }