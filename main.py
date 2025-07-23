from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
from dotenv import load_dotenv
from models import HealthResponse, HelloResponse
from routers import entities, ner, notability

# Load environment variables from .env file
load_dotenv()

# Debug: Check if API key is loaded (remove this in production)
api_key = os.getenv('OPENAI_API_KEY')
if api_key:
    print(f"✅ OpenAI API key loaded: {api_key[:10]}...")
else:
    print("❌ OpenAI API key not found in environment variables")

app = FastAPI(
    title="My FastAPI App",
    description="A simple FastAPI application with Named Entity Recognition",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Include routers
app.include_router(entities.router)
app.include_router(ner.router)
app.include_router(notability.router)

@app.get("/", response_model=HelloResponse)
def read_root():
    return HelloResponse()

@app.get("/health", response_model=HealthResponse)
def health_check():
    return HealthResponse()

 