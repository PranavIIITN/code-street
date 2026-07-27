"""FastAPI entrypoint for the Fleet Governance Layer demo."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.routes import router
from app.simulator import simulated_agent_traffic


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    init_db()
    simulator_task = asyncio.create_task(simulated_agent_traffic())
    try:
        yield
    finally:
        simulator_task.cancel()
        try:
            await simulator_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Agent Governance Layer", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

@app.get("/")
def serve_dashboard():
    if os.path.exists("frontend/dist/index.html"):
        return FileResponse("frontend/dist/index.html")
    if os.path.exists("dashboard.html"):
        return FileResponse("dashboard.html")
    return {"message": "Fleet Governance API"}

if os.path.exists("frontend/dist/assets"):
    app.mount("/assets", StaticFiles(directory="frontend/dist/assets"), name="assets")

app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
