from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from agent_script import create_graph, invoke_our_graph
import asyncio
import os
from contextlib import asynccontextmanager
from typing import List, Dict, Any
from dotenv import load_dotenv

# Load environment variables (for API keys)
load_dotenv()

# Create the agent once at startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting up... Creating Spotify agent...")
    app.state.agent = await create_graph()
    print("Agent created successfully!")
    yield  # Server is running
    print("Shutting down...")

# Create FastAPI app with lifecycle management
app = FastAPI(
    title="Spotify Agent API",
    description="A FastAPI backend for the Spotify agent",
    lifespan=lifespan
)

# Allow the HTML frontend to make requests to this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatQuery(BaseModel):
    message: str

@app.post("/chat")
async def chat(query: ChatQuery):
    agent = app.state.agent
    if agent is None:
        return {"error": "Agent not initialized"}
    response = await invoke_our_graph(agent, [{"role": "user", "content": query.message}])
    print(response)
    return {"response": response["messages"][-1].content}

@app.get("/")
async def serve_frontend():
    """Serve the HTML frontend."""
    html_path = os.path.join(os.path.dirname(__file__), "spotify_ai_agent_frontend.html")
    return FileResponse(html_path)