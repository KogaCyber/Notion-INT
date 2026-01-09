from fastapi import FastAPI, Request
import uvicorn
import logging
from datetime import datetime

app = FastAPI()

# Setup logging to file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/max/notion_webhook.log'),  # Save in your home directory
        logging.StreamHandler()
    ]
)

@app.get("/notion-webhook")
async def verify_webhook(request: Request):
    verification_token = request.query_params.get("verification")
    
    # Log to file AND console
    logging.info(f"=== NOTION VERIFICATION REQUEST ===")
    logging.info(f"Token: {verification_token}")
    logging.info(f"Time: {datetime.now()}")
    logging.info(f"Full URL: {request.url}")
    logging.info(f"IP: {request.client.host if request.client else 'Unknown'}")
    logging.info(f"====================================")
    
    # Also save to a simple text file
    with open("/home/max/verification_token.txt", "w") as f:
        f.write(f"{verification_token}")
    
    print(f"\n{'='*60}")
    print(f"TOKEN RECEIVED: {verification_token}")
    print(f"Check file: /home/max/verification_token.txt")
    print(f"{'='*60}\n")
    
    return {"status": "received"}

@app.post("/notion-webhook")
async def handle_webhook(request: Request):
    # For future webhook events
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)