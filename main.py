from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/callback")
async def callback(request: Request):
    body = await request.body()
    print("LINEから受信:", body)
    return "OK"
