from fastapi import APIRouter, HTTPException, Request
from typing import List
import json
import os
import fcntl
import time
from contextlib import contextmanager
from openai import OpenAI
from models import NotabilityData, CreateNotabilityRequest, ResearchRequest, ResearchResponse, ResearchStatusRequest, ResearchStatusResponse, NotabilityStatusRequest, NotabilityStatusResponse, TIMEOUT_SECONDS, MAX_RETRIES
from routers.entities import entities_store, save_entities, load_entities

# Create router for notability endpoints
router = APIRouter(
    prefix="/notability",
    tags=["notability"],
    responses={404: {"description": "Not found"}},
)

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
notability_file = "notability.txt"

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
                            # Migrate old data to include new fields
                            if 'research_request_timestamp' not in notability_data:
                                notability_data['research_request_timestamp'] = None
                            if 'notability_request_timestamp' not in notability_data:
                                notability_data['notability_request_timestamp'] = None
                            if 'retry_count' not in notability_data:
                                notability_data['retry_count'] = 0
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

def is_request_timed_out(timestamp: float) -> bool:
    """Check if a request has timed out based on its timestamp"""
    if timestamp is None:
        return False
    return time.time() - timestamp > TIMEOUT_SECONDS

def cancel_and_retry_research_request(entity_id: str, entity_data: dict) -> str:
    """Cancel a hanging research request and retry it"""
    print(f"[DEBUG] Cancelling and retrying research request for entity {entity_id}")
    
    # Cancel the hanging request
    try:
        if entity_data.get('openai_research_request_id'):
            client.responses.cancel(entity_data['openai_research_request_id'])
            print(f"[DEBUG] Cancelled research request: {entity_data['openai_research_request_id']}")
    except Exception as e:
        print(f"[DEBUG] Error cancelling research request: {str(e)}")
    
    # Get entity info for retry
    entity = entities_store[entity_id]
    canonical_name = entity.get('name', '')
    context = entity.get('context', '')
    
    # Create idempotency key based on entity ID and retry count
    retry_count = entity_data.get('retry_count', 0) + 1
    idempotency_key = f"research_{entity_id}_{retry_count}"
    
    # Retry the request
    try:
        response = client.responses.create(
            prompt={
                "id": "pmpt_687eaf8edda88194b8f2c14fa48e3a45059695391023684d",
                "version": "10",
                "variables": {
                    "entity_name": canonical_name,
                    "context": context
                }
            },
            background=True,
            idempotency_key=idempotency_key
        )
        
        # Update the notability data with new request ID and timestamp
        entity_data['openai_research_request_id'] = response.id
        entity_data['research_request_timestamp'] = time.time()
        entity_data['retry_count'] = retry_count
        notability_store[entity_id] = entity_data
        save_notability_data()
        
        print(f"[DEBUG] Retried research request with ID: {response.id}")
        return response.id
        
    except Exception as e:
        print(f"[DEBUG] Failed to retry research request: {str(e)}")
        # Mark as failed if we can't retry
        entity_data['openai_research_request_id'] = None
        entity_data['research_request_timestamp'] = None
        notability_store[entity_id] = entity_data
        save_notability_data()
        raise HTTPException(status_code=500, detail=f"Failed to retry research request: {str(e)}")

def cancel_and_retry_notability_request(entity_id: str, entity_data: dict) -> str:
    """Cancel a hanging notability request and retry it"""
    print(f"[DEBUG] Cancelling and retrying notability request for entity {entity_id}")
    
    # Cancel the hanging request
    try:
        if entity_data.get('openai_notability_request_id'):
            client.responses.cancel(entity_data['openai_notability_request_id'])
            print(f"[DEBUG] Cancelled notability request: {entity_data['openai_notability_request_id']}")
    except Exception as e:
        print(f"[DEBUG] Error cancelling notability request: {str(e)}")
    
    # Get entity info for retry
    entity = entities_store[entity_id]
    entity_name = entity.get('name', '')
    entity_context = entity.get('context', '')
    sources_str = json.dumps(entity_data.get('sources', []))
    
    # Create idempotency key based on entity ID and retry count
    retry_count = entity_data.get('retry_count', 0) + 1
    idempotency_key = f"notability_{entity_id}_{retry_count}"
    
    # Retry the request
    try:
        response = client.responses.create(
            prompt={
                "id": "pmpt_687ec395081c81969578b916f2d6a6d609eb423f8db71c55",
                "version": "5",
                "variables": {
                    "entity_name": entity_name,
                    "context": entity_context,
                    "sources": sources_str
                }
            },
            background=True,
            idempotency_key=idempotency_key
        )
        
        # Update the notability data with new request ID and timestamp
        entity_data['openai_notability_request_id'] = response.id
        entity_data['notability_request_timestamp'] = time.time()
        entity_data['retry_count'] = retry_count
        notability_store[entity_id] = entity_data
        save_notability_data()
        
        print(f"[DEBUG] Retried notability request with ID: {response.id}")
        return response.id
        
    except Exception as e:
        print(f"[DEBUG] Failed to retry notability request: {str(e)}")
        # Mark as failed if we can't retry
        entity_data['openai_notability_request_id'] = None
        entity_data['notability_request_timestamp'] = None
        notability_store[entity_id] = entity_data
        save_notability_data()
        raise HTTPException(status_code=500, detail=f"Failed to retry notability request: {str(e)}")

@router.post("/{entity_id}", response_model=NotabilityData)
def create_notability_research_job(entity_id: str):
    """Create a new research job for an entity - given an entity ID, start background research"""
    
    # Reload data to ensure we have the latest state
    load_notability_data()
    load_entities()
    
    # Check if research job has already been started
    if entity_id in notability_store:
        existing_data = notability_store[entity_id]
        if existing_data.get('openai_research_request_id') is not None:
            raise HTTPException(status_code=400, detail="Research job already exists for this entity")
    
    # Look up entity in entities store
    if entity_id not in entities_store:
        raise HTTPException(status_code=404, detail="Entity not found")
    
    entity = entities_store[entity_id]
    canonical_name = entity.get('name', '')
    context = entity.get('context', '')
    
    if not canonical_name or not context:
        raise HTTPException(status_code=400, detail="Entity missing required name or context")
    
    # Call OpenAI API with background=True
    try:
        response = client.responses.create(
            prompt={
                "id": "pmpt_687eaf8edda88194b8f2c14fa48e3a45059695391023684d",
                "version": "10",
                "variables": {
                    "entity_name": canonical_name,
                    "context": context
                }
            },
            background=True
        )
        
        # Extract the request ID
        openai_research_request_id = response.id
        
        # Update existing notability entry or create new one
        if entity_id in notability_store:
            notability_data = notability_store[entity_id]
            notability_data['openai_research_request_id'] = openai_research_request_id
            notability_data['research_request_timestamp'] = time.time()
        else:
            # Create new notability entry with null values except research_request_id
            notability_data = {
                'id': entity_id,
                'notability_status': None,
                'openai_research_request_id': openai_research_request_id,
                'research_request_timestamp': time.time(),
                'sources': [],
                'openai_notability_request_id': None,
                'notability_request_timestamp': None,
                'notability_rationale': None,
                'retry_count': 0
            }
        
        # Add/update in-memory store
        notability_store[entity_id] = notability_data
        
        # Update entity status to researching
        entities_store[entity_id]['status'] = 'researching'
        # Save entities to file using the proper function
        save_entities()
        
        # Save to file
        save_notability_data()
        
        return NotabilityData(**notability_data)
        
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
                "version": "10",
                "variables": {
                    "entity_name": canonical_name,
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
            notability_store[request.id]['research_request_timestamp'] = time.time()
        else:
            # Create new entry
            notability_data = {
                'id': request.id,
                'is_notable': None,
                'openai_research_request_id': openai_research_request_id,
                'research_request_timestamp': time.time(),
                'sources': [],
                'openai_notability_request_id': None,
                'notability_request_timestamp': None,
                'notability_status': None,
                'notability_rationale': None,
                'retry_count': 0
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
    
    print(f"[DEBUG] Checking research status for entity_id: {request.id}")
    print(f"[DEBUG] Request object: {request}")
    print(f"[DEBUG] Request type: {type(request)}")
    print(f"[DEBUG] Request dict: {request.dict()}")
    
    # Check if entity exists in notability store
    if request.id not in notability_store:
        print(f"[DEBUG] Entity {request.id} not found in notability store")
        raise HTTPException(status_code=404, detail="Entity not found in notability store")
    
    entity_data = notability_store[request.id]
    print(f"[DEBUG] Entity data: {entity_data}")
    
    openai_research_request_id = entity_data.get('openai_research_request_id')
    print(f"[DEBUG] OpenAI research request ID: {openai_research_request_id}")
    
    if not openai_research_request_id:
        print(f"[DEBUG] No research request ID found for entity {request.id}")
        # Check if entity exists in entities store to provide better error message
        if request.id in entities_store:
            raise HTTPException(status_code=400, detail="No research request found for this entity. Please start research first using POST /notability/{entity_id}")
        else:
            raise HTTPException(status_code=404, detail="Entity not found. Please create entity first.")
    
    # Check for timeout before making API call
    research_timestamp = entity_data.get('research_request_timestamp')
    retry_count = entity_data.get('retry_count', 0)
    
    if research_timestamp and is_request_timed_out(research_timestamp):
        print(f"[DEBUG] Research request timed out for entity {request.id}")
        
        if retry_count >= MAX_RETRIES:
            print(f"[DEBUG] Max retries exceeded for entity {request.id}, marking as failed")
            # Mark as failed
            entity_data['openai_research_request_id'] = None
            entity_data['research_request_timestamp'] = None
            notability_store[request.id] = entity_data
            save_notability_data()
            
            # Update entity status to failed
            entities_store[request.id]['status'] = 'failed'
            save_entities()
            
            return ResearchStatusResponse(
                status="failed",
                openai_research_request_id=openai_research_request_id,
                sources=None
            )
        else:
            # Retry the request
            print(f"[DEBUG] Retrying research request for entity {request.id} (attempt {retry_count + 1})")
            new_request_id = cancel_and_retry_research_request(request.id, entity_data)
            return ResearchStatusResponse(
                status="pending",
                openai_research_request_id=new_request_id,
                sources=None
            )
    
    try:
        print(f"[DEBUG] Calling OpenAI API to retrieve response for ID: {openai_research_request_id}")
        # Retrieve the response from OpenAI
        response = client.responses.retrieve(openai_research_request_id)
        print(f"[DEBUG] OpenAI response status: {response.status}")
        
        if response.status == 'completed':
            # Parse the response content for sources
            try:
                print(f"[DEBUG] Response object attributes: {dir(response)}")
                print(f"[DEBUG] Response object: {response}")
                
                # Extract the content from the response output
                content = None
                if hasattr(response, 'output') and response.output:
                    # Look for the last message in output that contains the JSON
                    for item in reversed(response.output):
                        if hasattr(item, 'content') and item.content:
                            for content_item in item.content:
                                if hasattr(content_item, 'text'):
                                    content = content_item.text
                                    break
                            if content:
                                break
                
                print(f"[DEBUG] Extracted content: {content}")
                
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
                
                # Update entity status to researched
                entities_store[request.id]['status'] = 'researched'
                # Save entities to file using the proper function
                save_entities()
                
                # Trigger notability evaluation
                try:
                    entity = entities_store[request.id]
                    entity_name = entity.get('name', '')
                    entity_context = entity.get('context', '')
                    
                    print(f"[DEBUG] Entity data for notability trigger: {entity}")
                    print(f"[DEBUG] Entity name: {entity_name}")
                    print(f"[DEBUG] Entity context: {entity_context}")
                    
                    # Convert sources to string format for the API
                    sources_str = json.dumps([source.dict() for source in sources])
                    print(f"[DEBUG] Sources string length: {len(sources_str)}")
                    
                    print(f"[DEBUG] Starting notability evaluation for {request.id}")
                    notability_response = client.responses.create(
                        prompt={
                            "id": "pmpt_687ec395081c81969578b916f2d6a6d609eb423f8db71c55",
                            "version": "5",
                            "variables": {
                                "entity_name": entity_name,
                                "context": entity_context,
                                "sources": sources_str
                            }
                        },
                        background=True
                    )
                    
                    # Update notability data with the notability request ID
                    entity_data['openai_notability_request_id'] = notability_response.id
                    entity_data['notability_request_timestamp'] = time.time()
                    notability_store[request.id] = entity_data
                    save_notability_data()
                    
                    print(f"[DEBUG] Notability evaluation started with ID: {notability_response.id}")
                    
                except Exception as e:
                    print(f"[DEBUG] Failed to start notability evaluation: {str(e)}")
                    print(f"[DEBUG] Exception type: {type(e)}")
                    import traceback
                    print(f"[DEBUG] Full traceback: {traceback.format_exc()}")
                    # Don't fail the research response if notability evaluation fails to start
                
                return ResearchStatusResponse(
                    status="completed",
                    openai_research_request_id=openai_research_request_id,
                    sources=sources
                )
                
            except json.JSONDecodeError as e:
                # If we can't parse the response, still return completed status and mark as researched
                entities_store[request.id]['status'] = 'researched'
                # Save entities to file using the proper function
                save_entities()
                
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
        print(f"[DEBUG] Exception in research status check: {str(e)}")
        print(f"[DEBUG] Exception type: {type(e)}")
        import traceback
        print(f"[DEBUG] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error checking research status: {str(e)}")

@router.post("/notability/trigger", response_model=dict)
def trigger_notability_evaluation(request: NotabilityStatusRequest):
    """Manually trigger notability evaluation for an entity that has completed research"""
    
    print(f"[DEBUG] Manually triggering notability evaluation for entity_id: {request.id}")
    
    # Check if entity exists in notability store
    if request.id not in notability_store:
        print(f"[DEBUG] Entity {request.id} not found in notability store")
        raise HTTPException(status_code=404, detail="Entity not found in notability store")
    
    entity_data = notability_store[request.id]
    
    # Check if research was completed
    if not entity_data.get('sources') or len(entity_data.get('sources', [])) == 0:
        raise HTTPException(status_code=400, detail="Research not completed. Please complete research first.")
    
    # Check if notability evaluation is already in progress
    if entity_data.get('openai_notability_request_id'):
        raise HTTPException(status_code=400, detail="Notability evaluation already in progress.")
    
    # Check if entity exists in entities store
    if request.id not in entities_store:
        raise HTTPException(status_code=404, detail="Entity not found in entities store")
    
    try:
        entity = entities_store[request.id]
        entity_name = entity.get('name', '')
        entity_context = entity.get('context', '')
        
        print(f"[DEBUG] Entity data for manual notability trigger: {entity}")
        print(f"[DEBUG] Entity name: {entity_name}")
        print(f"[DEBUG] Entity context: {entity_context}")
        
        # Convert sources to string format for the API
        sources_str = json.dumps([source for source in entity_data.get('sources', [])])
        print(f"[DEBUG] Sources string length: {len(sources_str)}")
        
        print(f"[DEBUG] Starting manual notability evaluation for {request.id}")
        notability_response = client.responses.create(
            prompt={
                "id": "pmpt_687ec395081c81969578b916f2d6a6d609eb423f8db71c55",
                "version": "5",
                "variables": {
                    "entity_name": entity_name,
                    "context": entity_context,
                    "sources": sources_str
                }
            },
            background=True
        )
        
        # Update notability data with the notability request ID
        entity_data['openai_notability_request_id'] = notability_response.id
        entity_data['notability_request_timestamp'] = time.time()
        notability_store[request.id] = entity_data
        save_notability_data()
        
        print(f"[DEBUG] Manual notability evaluation started with ID: {notability_response.id}")
        
        return {
            "message": "Notability evaluation started successfully",
            "notability_request_id": notability_response.id
        }
        
    except Exception as e:
        print(f"[DEBUG] Failed to start manual notability evaluation: {str(e)}")
        print(f"[DEBUG] Exception type: {type(e)}")
        import traceback
        print(f"[DEBUG] Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to start notability evaluation: {str(e)}")

@router.post("/notability/status", response_model=NotabilityStatusResponse)
def check_notability_status(request: NotabilityStatusRequest):
    """Check the status of a notability evaluation request and parse response if completed"""
    
    print(f"[DEBUG] Checking notability status for entity_id: {request.id}")
    
    # Check if entity exists in notability store
    if request.id not in notability_store:
        print(f"[DEBUG] Entity {request.id} not found in notability store")
        raise HTTPException(status_code=404, detail="Entity not found in notability store")
    
    entity_data = notability_store[request.id]
    print(f"[DEBUG] Entity data: {entity_data}")
    
    openai_notability_request_id = entity_data.get('openai_notability_request_id')
    print(f"[DEBUG] OpenAI notability request ID: {openai_notability_request_id}")
    
    if not openai_notability_request_id:
        print(f"[DEBUG] No notability request ID found for entity {request.id}")
        # Check if research was completed but notability evaluation failed to start
        if entity_data.get('sources') and len(entity_data.get('sources', [])) > 0:
            raise HTTPException(status_code=400, detail="Research completed but notability evaluation failed to start. Please retry the research status check to trigger notability evaluation.")
        else:
            raise HTTPException(status_code=400, detail="No notability request found for this entity. Please complete research first.")
    
    # Check for timeout before making API call
    notability_timestamp = entity_data.get('notability_request_timestamp')
    retry_count = entity_data.get('retry_count', 0)
    
    if notability_timestamp and is_request_timed_out(notability_timestamp):
        print(f"[DEBUG] Notability request timed out for entity {request.id}")
        
        if retry_count >= MAX_RETRIES:
            print(f"[DEBUG] Max retries exceeded for entity {request.id}, marking as failed")
            # Mark as failed
            entity_data['openai_notability_request_id'] = None
            entity_data['notability_request_timestamp'] = None
            entity_data['notability_status'] = 'failed'
            entity_data['notability_rationale'] = 'Request timed out after multiple retries'
            notability_store[request.id] = entity_data
            save_notability_data()
            
            return NotabilityStatusResponse(
                status="failed",
                openai_notability_request_id=openai_notability_request_id,
                notability_status="failed",
                notability_rationale="Request timed out after multiple retries"
            )
        else:
            # Retry the request
            print(f"[DEBUG] Retrying notability request for entity {request.id} (attempt {retry_count + 1})")
            new_request_id = cancel_and_retry_notability_request(request.id, entity_data)
            return NotabilityStatusResponse(
                status="pending",
                openai_notability_request_id=new_request_id,
                notability_status=None,
                notability_rationale=None
            )
    
    try:
        print(f"[DEBUG] Calling OpenAI API to retrieve notability response for ID: {openai_notability_request_id}")
        # Retrieve the response from OpenAI
        response = client.responses.retrieve(openai_notability_request_id)
        print(f"[DEBUG] OpenAI notability response status: {response.status}")
        
        if response.status == 'completed':
            # Parse the response content for notability evaluation
            try:
                print(f"[DEBUG] Notability response object: {response}")
                
                # Extract the content from the response output
                content = None
                if hasattr(response, 'output') and response.output:
                    # Look for the last message in output that contains the JSON
                    for item in reversed(response.output):
                        if hasattr(item, 'content') and item.content:
                            for content_item in item.content:
                                if hasattr(content_item, 'text'):
                                    content = content_item.text
                                    break
                            if content:
                                break
                
                print(f"[DEBUG] Extracted notability content: {content}")
                
                # Parse JSON content to extract notability evaluation
                if isinstance(content, str):
                    parsed_content = json.loads(content)
                else:
                    parsed_content = content
                
                # Extract notability status and rationale
                notability_status = parsed_content.get('notability_status', '')
                rationale = parsed_content.get('rationale', '')
                
                print(f"[DEBUG] Parsed notability_status: {notability_status}, rationale: {rationale}")
                
                # Update the notability store with the evaluation results
                entity_data['notability_status'] = notability_status
                entity_data['notability_rationale'] = rationale
                notability_store[request.id] = entity_data
                save_notability_data()
                
                print(f"[DEBUG] Updated notability data: notability_status={notability_status}, rationale={rationale}")
                
                return NotabilityStatusResponse(
                    status="completed",
                    openai_notability_request_id=openai_notability_request_id,
                    notability_status=notability_status,
                    notability_rationale=rationale
                )
                
            except json.JSONDecodeError as e:
                print(f"[DEBUG] Failed to parse notability response JSON: {str(e)}")
                return NotabilityStatusResponse(
                    status="completed",
                    openai_notability_request_id=openai_notability_request_id,
                    notability_status=None,
                    notability_rationale="Failed to parse evaluation response"
                )
                
        elif response.status == 'failed':
            print(f"[DEBUG] Notability evaluation failed")
            return NotabilityStatusResponse(
                status="failed",
                openai_notability_request_id=openai_notability_request_id,
                notability_status=None,
                notability_rationale=None
            )
        else:
            # Still pending/processing
            print(f"[DEBUG] Notability evaluation still pending")
            return NotabilityStatusResponse(
                status="pending",
                openai_notability_request_id=openai_notability_request_id,
                notability_status=None,
                notability_rationale=None
            )
            
    except Exception as e:
        print(f"[DEBUG] Exception in notability status check: {str(e)}")
        print(f"[DEBUG] Exception type: {type(e)}")
        import traceback
        print(f"[DEBUG] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error checking notability status: {str(e)}")

# Function to check if notability data exists (for use by other modules)
def notability_exists(entity_id: str) -> bool:
    """Check if notability data exists for an entity"""
    return entity_id in notability_store 