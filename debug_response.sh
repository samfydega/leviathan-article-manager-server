#!/bin/bash

# Simple wrapper script for debugging OpenAI responses
# Usage: ./debug_response.sh <response_id>

if [ $# -eq 0 ]; then
    echo "Usage: ./debug_response.sh <response_id>"
    echo "Example: ./debug_response.sh resp_6883bc604ad0819a94ac84e445bc74c70e2b5963dc91916d"
    exit 1
fi

# Activate virtual environment and run debug script
source venv/bin/activate && python debug_openai_response.py "$1" 