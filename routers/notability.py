from fastapi import APIRouter, HTTPException, Request
from typing import List, Optional, Dict, Any, Tuple
import json
import os
import fcntl
import time
from contextlib import contextmanager
from openai import OpenAI
from models import (
    NotabilityData, ResearchRequest, ResearchResponse, 
    ResearchStatusRequest, ResearchStatusResponse, NotabilityStatusRequest, 
    Source, TIMEOUT_SECONDS, MAX_RETRIES
)
from routers.entities import entities_store, save_entities, load_entities

# Debug flag for notability router
DEBUG_NOTABILITY = True

# Create router for notability endpoints
router = APIRouter(
    prefix="/notability",
    tags=["notability"],
    responses={404: {"description": "Not found"}},
)

# Constants
RESEARCH_PROMPT_ID = "pmpt_687eaf8edda88194b8f2c14fa48e3a45059695391023684d"
RESEARCH_PROMPT_VERSION = "10"

@contextmanager
def file_lock(filename, mode='r'):
    """Context manager for file locking to prevent concurrent writes"""
    f = open(filename, mode)
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield f
    finally:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        f.close()

# Simple key-value store - load from file into dictionary
notability_store = {}
notability_file = "data/notability.txt"

# Initialize OpenAI client
client = OpenAI()

# Load existing notability data from file (JSON format)
def load_notability_data():
    global notability_store
    if os.path.exists(notability_file):
        with file_lock(notability_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        notability_data = json.loads(line)
                        if 'id' in notability_data:
                            # Migrate old data to new schema
                            if 'research_request_timestamp' not in notability_data:
                                notability_data['research_request_timestamp'] = None
                            if 'retry_count' not in notability_data:
                                notability_data['retry_count'] = 0
                            
                            # Convert old notability_status to new is_notable
                            if 'notability_status' in notability_data:
                                old_status = notability_data['notability_status']
                                if old_status in ['exceeds', 'meets']:
                                    notability_data['is_notable'] = True
                                elif old_status == 'fails':
                                    notability_data['is_notable'] = False
                                else:
                                    notability_data['is_notable'] = None
                                del notability_data['notability_status']
                            
                            # Remove old fields that are no longer used (notability evaluation request)
                            notability_data.pop('openai_notability_request_id', None)
                            notability_data.pop('notability_request_timestamp', None)
                            notability_data.pop('notability_rationale', None)
                            
                            notability_store[notability_data['id']] = notability_data
                    except json.JSONDecodeError:
                        continue

# Save notability data to file
def save_notability_data():
    with file_lock(notability_file, 'w') as f:
        f.write("# Simple key-value store for notability data (JSON format)\n")
        for notability in notability_store.values():
            f.write(json.dumps(notability) + '\n')

# Load data on module import
load_notability_data()

# Save cleaned data back to file after migration
save_notability_data()

def is_request_timed_out(timestamp: float) -> bool:
    """Check if a request has timed out based on its timestamp"""
    if timestamp is None:
        return False
    return time.time() - timestamp > TIMEOUT_SECONDS

def validate_entity_exists(entity_id: str) -> Dict[str, Any]:
    """Validate that an entity exists and return its data"""
    if entity_id not in entities_store:
        raise HTTPException(status_code=404, detail="Entity not found")
    
    entity = entities_store[entity_id]
    canonical_name = entity.get('name', '')
    context = entity.get('context', '')
    
    if not canonical_name or not context:
        raise HTTPException(status_code=400, detail="Entity missing required name or context")
    
    return entity

def get_entity_data(entity_id: str) -> Dict[str, Any]:
    """Get entity data from notability store, creating if it doesn't exist"""
    if entity_id not in notability_store:
        # Create new notability entry
        notability_data = {
            'id': entity_id,
            'is_notable': None,
            'openai_research_request_id': None,
            'research_request_timestamp': None,
            'sources': [],
            'retry_count': 0
        }
        notability_store[entity_id] = notability_data
    
    return notability_store[entity_id]

def create_openai_request(
    entity_name: str, 
    context: str, 
    idempotency_key: Optional[str] = None
) -> str:
    """Create an OpenAI request for research"""
    prompt_config = {
        "id": RESEARCH_PROMPT_ID,
        "version": RESEARCH_PROMPT_VERSION,
        "variables": {
            "entity_name": entity_name,
            "context": context
        }
    }
    
    kwargs = {
        "prompt": prompt_config,
        "background": True
    }
    
    if idempotency_key:
        kwargs["idempotency_key"] = idempotency_key
    
    response = client.responses.create(**kwargs)
    return response.id

def extract_response_content(response) -> Optional[str]:
    """Extract content from OpenAI response"""
    if not hasattr(response, 'output') or not response.output:
        return None
    
    # Look for the last message in output that contains the JSON
    for item in reversed(response.output):
        if hasattr(item, 'content') and item.content:
            for content_item in item.content:
                if hasattr(content_item, 'text'):
                    return content_item.text
    return None

def parse_sources_from_response(content: str) -> List[Source]:
    """Parse sources from OpenAI response content"""
    try:
        if isinstance(content, str):
            parsed_content = json.loads(content)
        else:
            parsed_content = content
        
        sources_data = parsed_content.get('sources', [])
        sources = []
        
        for source_data in sources_data:
            try:
                source = Source(**source_data)
                sources.append(source)
            except Exception:
                # Skip invalid sources but continue processing
                continue
        
        return sources
    except json.JSONDecodeError:
        return []

def calculate_notability_status(sources: List[Source]) -> bool:
    """Calculate notability status based on sources"""
    meets_standards_count = sum(1 for source in sources if source.meets_standards)
    return meets_standards_count >= 2

def cancel_and_retry_request(entity_id: str, entity_data: dict) -> str:
    """Cancel a hanging research request and retry it"""
    if DEBUG_NOTABILITY:
        print(f"[DEBUG] Cancelling and retrying research request for entity {entity_id}")
    
    # Cancel the hanging request
    try:
        if entity_data.get('openai_research_request_id'):
            client.responses.cancel(entity_data['openai_research_request_id'])
            if DEBUG_NOTABILITY:
                print(f"[DEBUG] Cancelled research request: {entity_data['openai_research_request_id']}")
    except Exception as e:
        if DEBUG_NOTABILITY:
            print(f"[DEBUG] Error cancelling research request: {str(e)}")
    
    # Get entity info for retry
    entity = entities_store[entity_id]
    entity_name = entity.get('name', '')
    context = entity.get('context', '')
    
    # Create idempotency key based on entity ID and retry count
    retry_count = entity_data.get('retry_count', 0) + 1
    idempotency_key = f"research_{entity_id}_{retry_count}"
    
    # Retry the request
    try:
        new_request_id = create_openai_request(
            entity_name=entity_name,
            context=context,
            idempotency_key=idempotency_key
        )
        
        # Update the notability data with new request ID and timestamp
        entity_data['openai_research_request_id'] = new_request_id
        entity_data['research_request_timestamp'] = time.time()
        entity_data['retry_count'] = retry_count
        notability_store[entity_id] = entity_data
        save_notability_data()
        
        if DEBUG_NOTABILITY:
            print(f"[DEBUG] Retried research request with ID: {new_request_id}")
        return new_request_id
        
    except Exception as e:
        if DEBUG_NOTABILITY:
            print(f"[DEBUG] Failed to retry research request: {str(e)}")
        # Mark as failed if we can't retry
        entity_data['openai_research_request_id'] = None
        entity_data['research_request_timestamp'] = None
        notability_store[entity_id] = entity_data
        save_notability_data()
        raise HTTPException(status_code=500, detail=f"Failed to retry research request: {str(e)}")

def handle_request_timeout(entity_id: str, entity_data: dict, current_request_id: str):
    """Handle research request timeout and retry logic"""
    retry_count = entity_data.get('retry_count', 0)
    
    if retry_count >= MAX_RETRIES:
        if DEBUG_NOTABILITY:
            print(f"[DEBUG] Max retries exceeded for entity {entity_id}, marking as failed")
        # Mark as failed
        entity_data['openai_research_request_id'] = None
        entity_data['research_request_timestamp'] = None
        
        # Update entity status to failed
        update_entity_status(entity_id, {
            'state': 'failed',
            'phase': 'failed'
        })
        
        notability_store[entity_id] = entity_data
        save_notability_data()
        
        return "failed", current_request_id, None, None
    else:
        # Retry the request
        if DEBUG_NOTABILITY:
            print(f"[DEBUG] Retrying research request for entity {entity_id} (attempt {retry_count + 1})")
        new_request_id = cancel_and_retry_request(entity_id, entity_data)
        return "pending", new_request_id, None, None

def update_entity_status(entity_id: str, status: Any):
    """Update entity status and save to file"""
    # Ensure status is always in the proper dictionary format
    if isinstance(status, str):
        # Convert string status to dictionary format
        entities_store[entity_id]['status'] = {
            'state': status,
            'phase': None
        }
    else:
        # Already in dictionary format
        entities_store[entity_id]['status'] = status
    save_entities()

@router.post("/{entity_id}", response_model=NotabilityData)
def create_notability_research_job(entity_id: str):
    """Create a new research job for an entity - given an entity ID, start background research"""
    
    # Reload data to ensure we have the latest state
    load_notability_data()
    load_entities()
    
    # Get entity data, creating if it doesn't exist
    entity_data = get_entity_data(entity_id)
    
    # Check if research job has already been started
    if entity_data.get('openai_research_request_id') is not None:
        raise HTTPException(status_code=400, detail="Research job already exists for this entity")
    
    # Validate entity exists
    entity = validate_entity_exists(entity_id)
    
    # Create OpenAI request
    try:
        openai_research_request_id = create_openai_request(
            entity_name=entity.get('name', ''),
            context=entity.get('context', '')
        )
        
        # Update notability data
        entity_data['openai_research_request_id'] = openai_research_request_id
        entity_data['research_request_timestamp'] = time.time()
        notability_store[entity_id] = entity_data
        
        # Update entity status to notability with processing phase
        update_entity_status(entity_id, {
            'state': 'notability',
            'phase': 'processing'
        })
        
        # Save to file
        save_notability_data()
        
        return NotabilityData(**entity_data)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI API error: {str(e)}")

@router.get("/", response_model=List[NotabilityData])
def get_all_notability_data():
    """Get all notability data"""
    # Reload data to ensure we have the latest state
    load_notability_data()
    
    return [NotabilityData(**data) for data in notability_store.values()]

@router.get("/{entity_id}", response_model=NotabilityData)
def get_notability_data(entity_id: str):
    """Get notability data for a specific entity"""
    # Reload data to ensure we have the latest state
    load_notability_data()
    
    if entity_id in notability_store:
        return NotabilityData(**notability_store[entity_id])
    else:
        raise HTTPException(status_code=404, detail="Notability data not found")

@router.post("/research", response_model=ResearchResponse)
def research_entity(request: ResearchRequest):
    """Research an entity by looking up its canonical name and context, then calling OpenAI"""
    
    # Validate entity exists
    entity = validate_entity_exists(request.id)
    
    # Create OpenAI request
    try:
        openai_research_request_id = create_openai_request(
            entity_name=entity.get('name', ''),
            context=entity.get('context', '')
        )
        
        # Store the request ID in the notability store
        entity_data = get_entity_data(request.id)
        entity_data['openai_research_request_id'] = openai_research_request_id
        entity_data['research_request_timestamp'] = time.time()
        notability_store[request.id] = entity_data
        
        # Save to file
        save_notability_data()
        
        return ResearchResponse(openai_research_request_id=openai_research_request_id)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI API error: {str(e)}")

@router.post("/research/status", response_model=ResearchStatusResponse)
def check_research_status(request: ResearchStatusRequest):
    """Check the status of a research request and parse response if completed"""
    
    print(f"[DEBUG] Checking research status for entity_id: {request.id}")
    
    # Check if entity exists in notability store
    if request.id not in notability_store:
        print(f"[DEBUG] Entity {request.id} not found in notability store")
        raise HTTPException(status_code=404, detail="Entity not found in notability store")
    
    entity_data = notability_store[request.id]
    openai_research_request_id = entity_data.get('openai_research_request_id')
    
    if not openai_research_request_id:
        print(f"[DEBUG] No research request ID found for entity {request.id}")
        # Check if entity exists in entities store to provide better error message
        if request.id in entities_store:
            raise HTTPException(status_code=400, detail="No research request found for this entity. Please start research first using POST /notability/{entity_id}")
        else:
            raise HTTPException(status_code=404, detail="Entity not found. Please create entity first.")
    
    # Check for timeout before making API call
    research_timestamp = entity_data.get('research_request_timestamp')
    
    if research_timestamp and is_request_timed_out(research_timestamp):
        print(f"[DEBUG] Research request timed out for entity {request.id}")
        status, request_id, sources, rationale = handle_request_timeout(
            request.id, entity_data, openai_research_request_id
        )
        return ResearchStatusResponse(
            status=status,
            openai_research_request_id=request_id,
            sources=sources
        )
    
    try:
        print(f"[DEBUG] Calling OpenAI API to retrieve response for ID: {openai_research_request_id}")
        # Retrieve the response from OpenAI
        response = client.responses.retrieve(openai_research_request_id)
        print(f"[DEBUG] OpenAI response status: {response.status}")
        
        if response.status == 'completed':
            # Parse the response content for sources
            try:
                content = extract_response_content(response)
                print(f"[DEBUG] Extracted content: {content}")
                
                if content:
                    sources = parse_sources_from_response(content)
                    
                    # Update the notability store with the parsed sources
                    entity_data['sources'] = [source.dict() for source in sources]
                    notability_store[request.id] = entity_data
                    save_notability_data()
                    
                    # Automatically determine notability based on meets_standards count
                    try:
                        is_notable = calculate_notability_status(sources)
                        
                        # Update notability data with the determined status
                        entity_data['is_notable'] = is_notable
                        notability_store[request.id] = entity_data
                        save_notability_data()
                        
                        print(f"[DEBUG] Automatically determined notability: {is_notable}")
                        
                    except Exception as e:
                        print(f"[DEBUG] Failed to determine notability automatically: {str(e)}")
                        # Don't fail the research response if notability determination fails
                    
                    # Update entity status to notability with completed phase
                    update_entity_status(request.id, {
                        'state': 'notability',
                        'phase': 'completed'
                    })
                    
                    return ResearchStatusResponse(
                        status="completed",
                        openai_research_request_id=openai_research_request_id,
                        sources=sources
                    )
                else:
                    # If we can't parse the response, still return completed status and mark as notability
                    update_entity_status(request.id, {
                        'state': 'notability',
                        'phase': 'completed'
                    })
                    
                    return ResearchStatusResponse(
                        status="completed",
                        openai_research_request_id=openai_research_request_id,
                        sources=[]
                    )
                
            except json.JSONDecodeError as e:
                # If we can't parse the response, still return completed status and mark as notability
                update_entity_status(request.id, {
                    'state': 'notability',
                    'phase': 'completed'
                })
                
                return ResearchStatusResponse(
                    status="completed",
                    openai_research_request_id=openai_research_request_id,
                    sources=[]
                )
                
        elif response.status == 'failed':
            # Update entity status to failed
            update_entity_status(request.id, {
                'state': 'failed',
                'phase': 'failed'
            })
            
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
        print(f"[DEBUG] Exception in research status check: {str(e)}")
        import traceback
        print(f"[DEBUG] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error checking research status: {str(e)}")

@router.post("/notability/recalculate", response_model=dict)
def recalculate_notability(request: NotabilityStatusRequest):
    """Manually recalculate notability based on current sources (overrides automatic determination)"""
    
    print(f"[DEBUG] Manually recalculating notability for entity_id: {request.id}")
    
    # Check if entity exists in notability store
    if request.id not in notability_store:
        print(f"[DEBUG] Entity {request.id} not found in notability store")
        raise HTTPException(status_code=404, detail="Entity not found in notability store")
    
    entity_data = notability_store[request.id]
    
    # Check if research was completed
    if not entity_data.get('sources') or len(entity_data.get('sources', [])) == 0:
        raise HTTPException(status_code=400, detail="Research not completed. Please complete research first.")
    
    try:
        # Convert sources back to Source objects for processing
        sources = []
        for source_data in entity_data.get('sources', []):
            try:
                source = Source(**source_data)
                sources.append(source)
            except Exception:
                continue
        
        # Calculate notability status
        is_notable = calculate_notability_status(sources)
        meets_standards_count = sum(1 for source in sources if source.meets_standards)
        
        # Update notability data with the recalculated status
        entity_data['is_notable'] = is_notable
        notability_store[request.id] = entity_data
        save_notability_data()
        
        print(f"[DEBUG] Recalculated notability: {is_notable} ({meets_standards_count} sources meet standards)")
        
        return {
            "message": "Notability recalculated successfully",
            "is_notable": is_notable,
            "meets_standards_count": meets_standards_count
        }
        
    except Exception as e:
        print(f"[DEBUG] Failed to recalculate notability: {str(e)}")
        import traceback
        print(f"[DEBUG] Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to recalculate notability: {str(e)}")

# Function to check if notability data exists (for use by other modules)
def notability_exists(entity_id: str) -> bool:
    """Check if notability data exists for an entity"""
    return entity_id in notability_store 