from fastapi import FastAPI, Request
import uvicorn

app = FastAPI()

@app.get("/notion-webhook")
async def verify_webhook(request: Request):
    verification_token = request.query_params.get("verification")
    print(f"Verification token: {verification_token}")
    return {"status": "received"}

@app.post("/notion-webhook")
async def handle_webhook():
    # Handle actual webhook events
    return {"status": "ok"}