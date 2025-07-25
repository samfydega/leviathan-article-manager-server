from fastapi import APIRouter, HTTPException
from typing import List
import json
import os
import re
import fcntl
from contextlib import contextmanager
from models import CreateEntityRequest, EntityResponse, UpdateEntityStatusRequest, EntityStatus, ResearchedEntityResponse, Source

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
entities_file = "entities.txt"

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
                            entities_store[entity_data['id']] = entity_data
                    except json.JSONDecodeError:
                        continue

# Save entities to file
def save_entities():
    with file_lock(entities_file, 'w') as f:
        f.write("# Simple key-value store for entities (JSON format)\n")
        for entity in entities_store.values():
            f.write(json.dumps(entity) + '\n')

# Load entities on module import
load_entities()

@router.post("/", response_model=EntityResponse)
def create_entity(request: CreateEntityRequest):
    """Create a new entity with name, context, and status"""
    
    # Generate key from entity name
    entity_id = format_entity_key(request.entity_name)
    
    # Create entity data
    entity_data = {
        'id': entity_id,
        'name': request.entity_name,
        'context': request.entity_context,
        'status': request.status.value
    }
    
    # Add to in-memory store
    entities_store[entity_id] = entity_data
    
    # If status is queue, create notability entry if it doesn't exist
    if request.status.value == 'queue':
        from routers.notability import notability_exists, notability_store, save_notability_data
        
        if not notability_exists(entity_id):
            # Create notability entry with all null values
            notability_data = {
                'id': entity_id,
                'notability_status': None,
                'openai_research_request_id': None,
                'sources': [],
                'openai_notability_request_id': None,
                'notability_rationale': None
            }
            
            # Add to notability store
            notability_store[entity_id] = notability_data
            save_notability_data()
            
            print(f"[DEBUG] Created notability entry for new entity {entity_id} with queue status")
    
    # Save to file
    save_entities()
    
    return EntityResponse(**entity_data)

@router.get("/", response_model=List[EntityResponse])
def get_all_entities(status: str = None):
    """Get all entities in the store, optionally filtered by status"""
    # Reload data to ensure we have the latest state
    load_entities()
    
    all_entities = [EntityResponse(**entity_data) for entity_data in entities_store.values()]
    
    if status:
        # Filter by status if provided
        filtered_entities = [entity for entity in all_entities if entity.status == status]
        return filtered_entities
    
    return all_entities

@router.get("/status/researched", response_model=List[ResearchedEntityResponse])
def get_researched_entities_with_notability():
    """Get all researched entities with their notability data included"""
    
    from routers.notability import notability_store, load_notability_data
    
    # Load fresh notability data
    load_notability_data()
    
    researched_entities = []
    
    # Load fresh entity data from file to ensure we have latest
    if os.path.exists(entities_file):
        with open(entities_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        entity_data = json.loads(line)
                        # Check if entity has researched status
                        if entity_data.get('status') == 'researched':
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
                            researched_entity = ResearchedEntityResponse(
                                id=entity_data.get('id', ''),
                                name=entity_data.get('name', ''),
                                context=entity_data.get('context', ''),
                                status=EntityStatus(entity_data.get('status', 'researched')),
                                notability_status=notability_data.get('notability_status'),
                                notability_rationale=notability_data.get('notability_rationale'),
                                sources=sources
                            )
                            researched_entities.append(researched_entity)
                            
                    except json.JSONDecodeError:
                        continue
    
    return researched_entities

@router.get("/status/{status}", response_model=List[EntityResponse])
def get_entities_by_status(status: EntityStatus):
    """Get all entities with a specific status"""
    
    filtered_entities = []
    
    # Load fresh data from file to ensure we have latest
    if os.path.exists(entities_file):
        with open(entities_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        entity_data = json.loads(line)
                        # Check if entity has the requested status
                        if entity_data.get('status') == status.value:
                            filtered_entities.append(EntityResponse(**entity_data))
                    except json.JSONDecodeError:
                        continue
    
    return filtered_entities

@router.get("/queue", response_model=List[EntityResponse])
def get_queue_entities():
    """Get all entities with status 'queue'"""
    
    queue_entities = []
    
    # Load fresh data from file to ensure we have latest
    if os.path.exists(entities_file):
        with open(entities_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        entity_data = json.loads(line)
                        # Check if entity has queue status
                        if entity_data.get('status') == EntityStatus.queue.value:
                            queue_entities.append(EntityResponse(**entity_data))
                    except json.JSONDecodeError:
                        continue
    
    return queue_entities

@router.patch("/{entity_id}", response_model=EntityResponse)
def update_entity_status(entity_id: str, request: UpdateEntityStatusRequest):
    """Update the status of an entity by ID"""
    
    # Check if entity exists
    if entity_id not in entities_store:
        raise HTTPException(status_code=404, detail="Entity not found")
    
    # Update the status in memory
    entities_store[entity_id]['status'] = request.status.value
    
    # If status is being set to queue, create notability entry if it doesn't exist
    if request.status.value == 'queue':
        from routers.notability import notability_exists, notability_store, save_notability_data
        
        if not notability_exists(entity_id):
            # Create notability entry with all null values
            notability_data = {
                'id': entity_id,
                'notability_status': None,
                'openai_research_request_id': None,
                'sources': [],
                'openai_notability_request_id': None,
                'notability_rationale': None
            }
            
            # Add to notability store
            notability_store[entity_id] = notability_data
            save_notability_data()
            
            print(f"[DEBUG] Created notability entry for entity {entity_id} when status set to queue")
    
    # Save to file
    save_entities()
    
    # Return updated entity
    return EntityResponse(**entities_store[entity_id])

@router.get("/{entity_id}", response_model=EntityResponse)
def get_entity(entity_id: str):
    """Get a specific entity by ID"""
    if entity_id in entities_store:
        return EntityResponse(**entities_store[entity_id])
    else:
        raise HTTPException(status_code=404, detail="Entity not found")

# Function to check if entity exists (for use by other modules)
def entity_exists(entity_id: str) -> bool:
    """Check if an entity exists in the store"""
    return entity_id in entities_store 