from fastapi import APIRouter, HTTPException
from typing import List
import json
import os
from openai import OpenAI
from models import NotabilityData, CreateNotabilityRequest, ResearchRequest, ResearchResponse, ResearchStatusRequest, ResearchStatusResponse

# Create router for notability endpoints
router = APIRouter(
    prefix="/notability",
    tags=["notability"],
    responses={404: {"description": "Not found"}},
)

# Simple key-value store - load from file into dictionary
notability_store = {}
notability_file = "notability.txt"

# Entity store for lookup
entities_store = {}
entities_file = "entities.txt"

# Initialize OpenAI client
client = OpenAI()

# Load existing notability data from file (JSON format)
def load_notability_data():
    global notability_store
    if os.path.exists(notability_file):
        with open(notability_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        notability_data = json.loads(line)
                        if 'id' in notability_data:
                            notability_store[notability_data['id']] = notability_data
                    except json.JSONDecodeError:
                        continue

# Save notability data to file
def save_notability_data():
    with open(notability_file, 'w') as f:
        f.write("# Simple key-value store for notability data (JSON format)\n")
        for notability in notability_store.values():
            f.write(json.dumps(notability) + '\n')

# Load entities data from file (JSON format)
def load_entities_data():
    global entities_store
    if os.path.exists(entities_file):
        with open(entities_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        entity_data = json.loads(line)
                        if 'id' in entity_data:
                            entities_store[entity_data['id']] = entity_data
                    except json.JSONDecodeError:
                        continue

# Load data on module import
load_notability_data()
load_entities_data()

@router.post("/", response_model=NotabilityData)
def create_notability_data(request: CreateNotabilityRequest):
    """Create notability data for an entity"""
    
    # Create notability data
    notability_data = {
        'id': request.entity_id,
        'is_notable': request.is_notable,
        'openai_research_request_id': request.openai_research_request_id,
        'sources': [source.dict() for source in request.sources],
        'openai_notability_request_id': request.openai_notability_request_id
    }
    
    # Add to in-memory store
    notability_store[request.entity_id] = notability_data
    
    # Save to file
    save_notability_data()
    
    return NotabilityData(**notability_data)

@router.get("/", response_model=List[NotabilityData])
def get_all_notability_data():
    """Get all notability data"""
    return [NotabilityData(**data) for data in notability_store.values()]

@router.get("/{entity_id}", response_model=NotabilityData)
def get_notability_data(entity_id: str):
    """Get notability data for a specific entity"""
    if entity_id in notability_store:
        return NotabilityData(**notability_store[entity_id])
    else:
        raise HTTPException(status_code=404, detail="Notability data not found")

@router.post("/research", response_model=ResearchResponse)
def research_entity(request: ResearchRequest):
    """Research an entity by looking up its canonical name and context, then calling OpenAI"""
    
    # Look up entity in entities store
    if request.id not in entities_store:
        raise HTTPException(status_code=404, detail="Entity not found")
    
    entity = entities_store[request.id]
    canonical_name = entity.get('name', '')
    context = entity.get('context', '')
    
    if not canonical_name or not context:
        raise HTTPException(status_code=400, detail="Entity missing required name or context")
    
    # Call OpenAI API with background=True
    try:
        response = client.responses.create(
            prompt={
                "id": "pmpt_687eaf8edda88194b8f2c14fa48e3a45059695391023684d",
                "version": "8",
                "variables": {
                    "canonical_name": canonical_name,
                    "context": context
                }
            },
            background=True
        )
        
        # Extract the request ID
        openai_research_request_id = response.id
        
        # Store the request ID in the notability store
        if request.id in notability_store:
            notability_store[request.id]['openai_research_request_id'] = openai_research_request_id
        else:
            # Create new entry
            notability_data = {
                'id': request.id,
                'is_notable': None,
                'openai_research_request_id': openai_research_request_id,
                'sources': [],
                'openai_notability_request_id': None
            }
            notability_store[request.id] = notability_data
        
        # Save to file
        save_notability_data()
        
        return ResearchResponse(openai_research_request_id=openai_research_request_id)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI API error: {str(e)}")

@router.post("/research/status", response_model=ResearchStatusResponse)
def check_research_status(request: ResearchStatusRequest):
    """Check the status of a research request and parse response if completed"""
    
    # Check if entity exists in notability store
    if request.id not in notability_store:
        raise HTTPException(status_code=404, detail="Entity not found in notability store")
    
    entity_data = notability_store[request.id]
    openai_research_request_id = entity_data.get('openai_research_request_id')
    
    if not openai_research_request_id:
        raise HTTPException(status_code=400, detail="No research request found for this entity")
    
    try:
        # Retrieve the response from OpenAI
        response = client.responses.retrieve(openai_research_request_id)
        
        if response.status == 'completed':
            # Parse the response content for sources
            try:
                # Extract the content from the response
                content = response.content
                
                # Parse JSON content to extract sources array
                if isinstance(content, str):
                    parsed_content = json.loads(content)
                else:
                    parsed_content = content
                
                # Extract sources array from the parsed content
                sources_data = parsed_content.get('sources', [])
                
                # Convert to Source objects
                from models import Source
                sources = []
                for source_data in sources_data:
                    try:
                        source = Source(**source_data)
                        sources.append(source)
                    except Exception as e:
                        # Skip invalid sources but continue processing
                        continue
                
                # Update the notability store with the parsed sources
                entity_data['sources'] = [source.dict() for source in sources]
                notability_store[request.id] = entity_data
                save_notability_data()
                
                return ResearchStatusResponse(
                    status="completed",
                    openai_research_request_id=openai_research_request_id,
                    sources=sources
                )
                
            except json.JSONDecodeError as e:
                # If we can't parse the response, still return completed status
                return ResearchStatusResponse(
                    status="completed",
                    openai_research_request_id=openai_research_request_id,
                    sources=[]
                )
                
        elif response.status == 'failed':
            return ResearchStatusResponse(
                status="failed",
                openai_research_request_id=openai_research_request_id,
                sources=None
            )
        else:
            # Still pending/processing
            return ResearchStatusResponse(
                status="pending",
                openai_research_request_id=openai_research_request_id,
                sources=None
            )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error checking research status: {str(e)}")

# Function to check if notability data exists (for use by other modules)
def notability_exists(entity_id: str) -> bool:
    """Check if notability data exists for an entity"""
    return entity_id in notability_store 