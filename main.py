from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import os
from dotenv import load_dotenv
from models import HealthResponse, HelloResponse
from routers import entities, ner, notability, drafts

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
app.include_router(drafts.router)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors and log the details"""
    print(f"[DEBUG] Validation error occurred!")
    print(f"[DEBUG] Request URL: {request.url}")
    print(f"[DEBUG] Request method: {request.method}")
    print(f"[DEBUG] Validation errors: {exc.errors()}")
    
    # Try to read the request body
    try:
        body = await request.body()
        print(f"[DEBUG] Request body: {body}")
        if body:
            print(f"[DEBUG] Request body (decoded): {body.decode('utf-8')}")
    except Exception as e:
        print(f"[DEBUG] Could not read request body: {e}")
    
    # Also log headers to see if Content-Type is correct
    print(f"[DEBUG] Content-Type header: {request.headers.get('content-type')}")
    
    return JSONResponse(
        status_code=400,
        content={"detail": "Validation error", "errors": exc.errors()}
    )

@app.get("/", response_model=HelloResponse)
def read_root():
    return HelloResponse()

@app.get("/health", response_model=HealthResponse)
def health_check():
    return HealthResponse()

 