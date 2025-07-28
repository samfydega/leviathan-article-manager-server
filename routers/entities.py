from fastapi import APIRouter, HTTPException
from typing import List, Optional
import json
import os
import re
import fcntl
from contextlib import contextmanager
from openai import OpenAI
from dotenv import load_dotenv
from models import (
    CreateEntityRequest, EntityResponse, UpdateEntityStatusRequest, 
    EntityStatus, NotabilityEntityResponse, Source, NERRequest, 
    NERResponse, Entity, EntityStatusObject, EntityPhase
)

# Debug flag for entities router
DEBUG_ENTITIES = False

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI()

# Create router for entity endpoints
router = APIRouter(
    prefix="/entities",
    tags=["entities"],
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

# Simple helper function to format entity names as keys
def format_entity_key(text):
    # Remove commas, convert to lowercase, replace spaces with hyphens
    return re.sub(r'[,\s]+', '-', text.lower()).strip('-')

# Simple key-value store - load from file into dictionary
entities_store = {}
entities_file = "data/entities.txt"

# Load existing entities from file (JSON format)
def load_entities():
    global entities_store
    if os.path.exists(entities_file):
        with file_lock(entities_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        entity_data = json.loads(line)
                        if 'id' in entity_data:
                            # Normalize status to ensure it's always a dictionary
                            entity_data = normalize_entity_status(entity_data)
                            entities_store[entity_data['id']] = entity_data
                    except json.JSONDecodeError:
                        continue

def normalize_entity_status(entity_data: dict) -> dict:
    """Normalize entity status to ensure it's always a dictionary with state and phase"""
    status = entity_data.get('status', {})
    if isinstance(status, str):
        # Convert string status to dictionary format
        entity_data['status'] = {
            'state': status,
            'phase': None
        }
    elif not isinstance(status, dict):
        # Handle None or other types
        entity_data['status'] = {
            'state': None,
            'phase': None
        }
    return entity_data

def get_entity_status_info(entity_data: dict) -> tuple:
    """Get state and phase from entity status, handling both string and dictionary formats"""
    status = entity_data.get('status', {})
    if isinstance(status, str):
        return status, None
    elif isinstance(status, dict):
        return status.get('state'), status.get('phase')
    else:
        return None, None

# Save entities to file
def save_entities():
    with file_lock(entities_file, 'w') as f:
        f.write("# Simple key-value store for entities (JSON format)\n")
        for entity in entities_store.values():
            f.write(json.dumps(entity) + '\n')

# Helper function to read entities from file with filtering
def read_entities_from_file(filter_func=None):
    """Read entities from file with optional filtering"""
    entities = []
    if os.path.exists(entities_file):
        with open(entities_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        entity_data = json.loads(line)
                        if filter_func is None or filter_func(entity_data):
                            entities.append(entity_data)
                    except json.JSONDecodeError:
                        continue
    return entities

# Helper function to create notability entry
def create_notability_entry(entity_id: str):
    """Create a notability entry for an entity"""
    from routers.notability import notability_exists, notability_store, save_notability_data
    
    if not notability_exists(entity_id):
        notability_data = {
            'id': entity_id,
            'is_notable': None,
            'openai_research_request_id': None,
            'research_request_timestamp': None,
            'sources': [],
            'retry_count': 0
        }
        
        notability_store[entity_id] = notability_data
        save_notability_data()
        if DEBUG_ENTITIES:
            print(f"[DEBUG] Created notability entry for entity {entity_id}")

# Helper function to remove entity from file
def remove_entity_from_file(file_path: str, entity_id: str, header: str):
    """Remove an entity from a specific file"""
    if os.path.exists(file_path):
        items_to_keep = []
        with file_lock(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        item_data = json.loads(line)
                        if item_data.get('id') != entity_id:
                            items_to_keep.append(line)
                    except json.JSONDecodeError:
                        continue
        
        with file_lock(file_path, 'w') as f:
            f.write(f"{header}\n")
            for item_line in items_to_keep:
                f.write(item_line + '\n')

# Load entities on module import
load_entities()

@router.post("/", response_model=EntityResponse)
def create_entity(request: CreateEntityRequest):
    """Create a new entity with name, context, entity_type, and status"""
    
    # Generate key from entity name
    entity_id = format_entity_key(request.entity_name)
    
    # Create entity data
    entity_data = {
        'id': entity_id,
        'name': request.entity_name,
        'context': request.entity_context,
        'entity_type': request.entity_type,
        'status': {
            'state': request.status.state.value if request.status.state else None,
            'phase': request.status.phase.value if request.status.phase else None
        }
    }
    
    # Add to in-memory store
    entities_store[entity_id] = entity_data
    
    # If status state is notability, create notability entry if it doesn't exist
    if request.status.state and request.status.state.value == 'notability':
        create_notability_entry(entity_id)
    
    # Save to file
    save_entities()
    
    return EntityResponse(**entity_data)

@router.get("/", response_model=List[EntityResponse])
def get_all_entities(status: str = None):
    """Get all entities in the store, optionally filtered by status state"""
    # Reload data to ensure we have the latest state
    load_entities()
    
    all_entities = [EntityResponse(**entity_data) for entity_data in entities_store.values()]
    
    if status:
        # Filter by status state if provided
        filtered_entities = [entity for entity in all_entities if entity.status.state == status]
        return filtered_entities
    
    return all_entities

@router.get("/status/notability", response_model=List[NotabilityEntityResponse])
def get_notability_entities():
    """Get all entities with notability status and their notability data included"""
    
    from routers.notability import notability_store, load_notability_data
    
    # Load fresh notability data
    load_notability_data()
    
    # Filter function for notability entities
    def is_notability(entity_data):
        entity_state, _ = get_entity_status_info(entity_data)
        return entity_state == 'notability'
    
    # Get notability entities using helper function
    notability_entity_data = read_entities_from_file(is_notability)
    
    notability_entities = []
    for entity_data in notability_entity_data:
        entity_id = entity_data.get('id')
        
        # Get notability data if it exists
        notability_data = notability_store.get(entity_id, {})
        
        # Convert sources from dict format to Source objects
        sources_data = notability_data.get('sources', [])
        sources = []
        for source_data in sources_data:
            try:
                if isinstance(source_data, dict):
                    sources.append(Source(**source_data))
            except Exception:
                # Skip invalid sources
                continue
        
        # Create combined response
        notability_entity = NotabilityEntityResponse(
            id=entity_data.get('id', ''),
            name=entity_data.get('name', ''),
            context=entity_data.get('context', ''),
            entity_type=entity_data.get('entity_type', 'UNKNOWN'),
            status=EntityStatusObject(
                state=EntityStatus(entity_data.get('status', {}).get('state', 'notability')) if entity_data.get('status', {}).get('state') else None,
                phase=EntityPhase(entity_data.get('status', {}).get('phase', 'processing')) if entity_data.get('status', {}).get('phase') else None
            ),
            is_notable=notability_data.get('is_notable'),
            sources=sources
        )
        notability_entities.append(notability_entity)
    
    return notability_entities

@router.get("/status", response_model=List[EntityResponse])
def get_entities_by_status(state: Optional[str] = None, phase: Optional[str] = None):
    """Get entities filtered by status state and/or phase using query parameters"""
    
    # Filter function for specific state and/or phase
    def matches_filter(entity_data):
        entity_state, entity_phase = get_entity_status_info(entity_data)
        
        # If both state and phase are specified, both must match
        if state and phase:
            return entity_state == state and entity_phase == phase
        # If only state is specified
        elif state:
            return entity_state == state
        # If only phase is specified
        elif phase:
            return entity_phase == phase
        # If neither is specified, return all entities
        else:
            return True
    
    # Get entities using helper function
    filtered_entity_data = read_entities_from_file(matches_filter)
    
    return [EntityResponse(**entity_data) for entity_data in filtered_entity_data]

@router.get("/status/{status}", response_model=List[EntityResponse])
def get_entities_by_status_legacy(status: str):
    """Legacy endpoint: Get entities by status state (treats path parameter as state)"""
    
    # Filter function for specific state
    def matches_state(entity_data):
        entity_state, _ = get_entity_status_info(entity_data)
        return entity_state == status
    
    # Get entities using helper function
    filtered_entity_data = read_entities_from_file(matches_state)
    
    return [EntityResponse(**entity_data) for entity_data in filtered_entity_data]

@router.get("/backlogged", response_model=List[EntityResponse])
def get_backlogged_entities():
    """Get all entities with status state 'backlogged'"""
    
    # Filter function for backlogged entities
    def is_backlogged(entity_data):
        entity_state, _ = get_entity_status_info(entity_data)
        return entity_state == EntityStatus.backlogged.value
    
    # Get backlogged entities using helper function
    backlogged_entity_data = read_entities_from_file(is_backlogged)
    
    return [EntityResponse(**entity_data) for entity_data in backlogged_entity_data]

@router.patch("/{entity_id}", response_model=EntityResponse)
def update_entity_status(entity_id: str, request: UpdateEntityStatusRequest):
    """Update the status of an entity by ID"""
    
    # Check if entity exists
    if entity_id not in entities_store:
        raise HTTPException(status_code=404, detail="Entity not found")
    
    # Update the status in memory
    entities_store[entity_id]['status'] = {
        'state': request.status.state.value if request.status.state else None,
        'phase': request.status.phase.value if request.status.phase else None
    }
    
    # If status state is being set to notability, create notability entry if it doesn't exist
    if request.status.state and request.status.state.value == 'notability':
        create_notability_entry(entity_id)
    
    # Save to file
    save_entities()
    
    # Return updated entity
    return EntityResponse(**entities_store[entity_id])

@router.delete("/{entity_id}")
def delete_entity(entity_id: str):
    """Delete an entity and all its related data from the system"""
    
    # Check if entity exists
    if entity_id not in entities_store:
        raise HTTPException(status_code=404, detail="Entity not found")
    
    # Remove from in-memory store
    deleted_entity = entities_store.pop(entity_id)
    
    # Save updated entities to file
    save_entities()
    
    # Remove from data/notability.txt if it exists
    try:
        from routers.notability import notability_store, save_notability_data
        
        if entity_id in notability_store:
            notability_store.pop(entity_id)
            save_notability_data()
            if DEBUG_ENTITIES:
                print(f"[DEBUG] Removed notability data for entity {entity_id}")
    except Exception as e:
        print(f"[WARNING] Error removing notability data for {entity_id}: {e}")
    
    # Remove from data/drafts_research.txt if it exists
    try:
        from routers.drafts import research_drafts_store, save_research_drafts
        
        if entity_id in research_drafts_store:
            research_drafts_store.pop(entity_id)
            save_research_drafts()
            if DEBUG_ENTITIES:
                print(f"[DEBUG] Removed research draft data for entity {entity_id}")
    except Exception as e:
        print(f"[WARNING] Error removing research draft data for {entity_id}: {e}")
    
    # Remove from data/drafts_writing.txt if it exists
    try:
        from routers.drafts import writing_drafts_store, save_writing_drafts
        
        if entity_id in writing_drafts_store:
            writing_drafts_store.pop(entity_id)
            save_writing_drafts()
            if DEBUG_ENTITIES:
                print(f"[DEBUG] Removed writing draft data for entity {entity_id}")
    except Exception as e:
        print(f"[WARNING] Error removing writing draft data for {entity_id}: {e}")
    
    # Remove from data/articles.txt if it exists
    try:
        articles_file = "data/articles.txt"
        if os.path.exists(articles_file):
            remove_entity_from_file(articles_file, entity_id, "# Articles KV store - ID -> {status, text}")
            
            if DEBUG_ENTITIES:
                print(f"[DEBUG] Removed article data for entity {entity_id}")
    except Exception as e:
        print(f"[WARNING] Error removing article data for {entity_id}: {e}")
    
    return {
        "message": f"Entity '{entity_id}' and all related data have been deleted",
        "deleted_entity": EntityResponse(**deleted_entity)
    }

@router.get("/{entity_id}", response_model=EntityResponse)
def get_entity(entity_id: str):
    """Get a specific entity by ID"""
    if entity_id in entities_store:
        return EntityResponse(**entities_store[entity_id])
    else:
        raise HTTPException(status_code=404, detail="Entity not found")

@router.post("/extract", response_model=NERResponse)
async def extract_entities_from_text(request: NERRequest):
    """Extract named entities from text using OpenAI, returning only entities not already in the database"""
    
    try:
        # Use the exact OpenAI API call structure provided
        response = client.responses.create(
            prompt={
                "id": "pmpt_687e9a02edfc8193ab9fcc4cd3508f5c0fba5ac419ccbf53",
                "version": "9",
                "variables": {
                    "text": request.text
                }
            }
        )

        if hasattr(response, 'output') and response.output:
            output_message = response.output[0]  # Get first output message
            
            if hasattr(output_message, 'content') and output_message.content:
                content_item = output_message.content[0]  # Get first content item
                
                if hasattr(content_item, 'text'):
                    response_text = content_item.text
                else:
                    raise Exception("No text found in content item")
            else:
                raise Exception("No content found in output message")
        else:
            raise Exception("No output found in response")
        
        entities_data = json.loads(response_text)

        # NER entity type constants
        FILTERED_OUT_TYPES = {
            "LANGUAGE", "DATE", "TIME", "PERCENT", "MONEY", 
            "QUANTITY", "ORDINAL", "CARDINAL"
        }
        
        ACCEPTED_TYPES = {
            "PERSON", "NORP", "FAC", "ORG", "GPE", "LOC", 
            "PRODUCT", "EVENT", "WORK_OF_ART", "LAW"
        }
        
        entities = []
        
        # Check if we have valid entities data
        if isinstance(entities_data, dict) and "entities" in entities_data and isinstance(entities_data["entities"], list):
            for entity_data in entities_data["entities"]:
                if isinstance(entity_data, dict) and "type" in entity_data and "value" in entity_data:
                    entity_type = entity_data["type"]
                    entity_value = entity_data["value"]
                    
                    # Filter out unwanted entity types - keep only meaningful entities like PERSON, ORG, etc.
                    if entity_type not in FILTERED_OUT_TYPES:
                        # Convert entity value to our ID format and check if it already exists
                        entity_id = format_entity_key(entity_value)
                        
                        # Only add entity if it's not already in our store
                        if not entity_exists(entity_id):
                            entity = Entity(type=entity_type, value=entity_value)
                            entities.append(entity)
        
        # Always return a valid response, even if entities list is empty
        return NERResponse(entities=entities)
        
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse OpenAI response as JSON: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing entity extraction request: {str(e)}")

# Function to check if entity exists (for use by other modules)
def entity_exists(entity_id: str) -> bool:
    """Check if an entity exists in the store"""
    return entity_id in entities_store 