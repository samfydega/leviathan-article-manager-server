# FastAPI Project

A FastAPI application with uvicorn server, fast reload, and Named Entity Recognition using OpenAI.

## Setup

1. **Create and activate virtual environment:**

   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Set up OpenAI API Key:**
   ```bash
   export OPENAI_API_KEY="your_openai_api_key_here"
   ```

## Running the Application

### Development (with fast reload):

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Using the development script:

```bash
./run_dev.sh
```

### Production:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

## API Documentation

Once the server is running, you can access:

- **Interactive API docs (Swagger UI):** http://localhost:8000/docs
- **Alternative API docs (ReDoc):** http://localhost:8000/redoc
- **OpenAPI JSON:** http://localhost:8000/openapi.json

## Available Endpoints

### Basic Endpoints

- `GET /` - Hello World
- `GET /items/{item_id}` - Get item by ID
- `POST /items/` - Create new item
- `GET /health` - Health check

### Named Entity Recognition

- `POST /ner` - Extract named entities from text using OpenAI

#### NER Request Format:

```json
{
  "text": "Apple Inc. was founded by Steve Jobs in Cupertino, California on April 1, 1976."
}
```

#### NER Response Format:

```json
{
  "entities": [
    {
      "type": "ORG",
      "value": "Apple Inc."
    },
    {
      "type": "PERSON",
      "value": "Steve Jobs"
    },
    {
      "type": "GPE",
      "value": "Cupertino"
    },
    {
      "type": "GPE",
      "value": "California"
    },
    {
      "type": "DATE",
      "value": "April 1, 1976"
    }
  ]
}
```

#### Supported Entity Types:

- `PERSON` - People, including fictional
- `NORP` - Nationalities or religious or political groups
- `FAC` - Buildings, airports, highways, bridges, etc.
- `ORG` - Companies, agencies, institutions, etc.
- `GPE` - Countries, cities, states
- `LOC` - Non-GPE locations, mountain ranges, bodies of water
- `PRODUCT` - Objects, vehicles, foods, etc. (not services)
- `EVENT` - Named hurricanes, battles, wars, sports events, etc.
- `WORK_OF_ART` - Titles of books, songs, movies, etc.
- `LAW` - Named documents made into laws
- `LANGUAGE` - Any named language
- `DATE` - Absolute or relative dates or periods
- `TIME` - Times smaller than a day
- `PERCENT` - Percentage, including "%"
- `MONEY` - Monetary values, including unit
- `QUANTITY` - Measurements, as of weight or distance
- `ORDINAL` - "first", "second", etc.
- `CARDINAL` - Numerals that do not fall under another type

## Example Usage

```bash
# Test the basic API
curl http://localhost:8000/
curl http://localhost:8000/items/1?q=test
curl -X POST "http://localhost:8000/items/" -H "Content-Type: application/json" -d '{"name":"Laptop","price":999.99}'

# Test Named Entity Recognition
curl -X POST "http://localhost:8000/ner" \
  -H "Content-Type: application/json" \
  -d '{"text": "Apple Inc. was founded by Steve Jobs in Cupertino, California on April 1, 1976."}'
```

## Requirements

- Python 3.8+
- OpenAI API Key
- FastAPI
- Uvicorn
- OpenAI Python client
