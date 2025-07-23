#!/bin/bash

# Activate virtual environment
source venv/bin/activate

# Start FastAPI server with fast reload
echo "Starting FastAPI development server with fast reload..."
echo "Server will be available at: http://localhost:8000"
echo "API Documentation: http://localhost:8000/docs"
echo "Press Ctrl+C to stop the server"
echo

uvicorn main:app --reload --host 0.0.0.0 --port 8000 