from fastapi import FastAPI
from app.api.routes import router

app = FastAPI(title="BI Agent")

app.include_router(router)