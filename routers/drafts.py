from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Optional, Literal, List, Any
import json
import os
import asyncio
import uuid
from datetime import datetime
import fcntl
from contextlib import contextmanager
from openai import OpenAI

from .notability import notability_store, notability_exists

router = APIRouter(
    prefix="/drafts",
    tags=["drafts"],
    responses={404: {"description": "Not found"}},
)

# Initialize OpenAI client
client = OpenAI()

# Store for entities, drafts, and articles
entities_store: Dict[str, dict] = {}
entities_file = "entities.txt"
drafts_store: Dict[str, dict] = {}
drafts_file = "drafts.txt"
articles_store: Dict[str, dict] = {}
articles_file = "articles.txt"

EntityType = Literal["venture_capitalist", "startup_founder", "startup_company", "venture_firm"]

# Prompt IDs for different research sections - FINAL VERSION
PROMPT_IDS = {
    "early_life": "pmpt_6881597633e08193a2ea8b886f8aa8990e7ece07212aea25",
    "pre_vc_career": "pmpt_68816c05988c8193856a632187c8fe4d08d13066f2175710",
    "vc_career": "pmpt_68816c254784819792b04926ab25312c0ae69cb869929a41",
    "notable_investments": "pmpt_68816c4c78fc8190858a214948b257940b4a7c7d059861df",
    "personal_life": "pmpt_68816c6a82a8819687e1eeda14f1a9480ae9ac0c76914685"
}

# Article drafting prompt
ARTICLE_DRAFT_PROMPT_ID = "pmpt_688182dcd80081939d8bef19645b0a4d0ed9043fd95e9430"

class CreateDraftRequest(BaseModel):
    id: str
    type: EntityType

class DraftStatus(BaseModel):
    id: str
    type: EntityType
    statuses: Dict[str, Optional[str]]
    results: Dict[str, Optional[Any]]
    created_at: str
    updated_at: str

class DraftProgressResponse(BaseModel):
    id: str
    total_sections: int
    completed_sections: int
    pending_sections: int
    progress_percentage: float
    updated_sections: List[str]
    is_complete: bool

class PageInfo(BaseModel):
    page_title: str
    url: str
    description: str

class ResearchResult(BaseModel):
    pages: List[PageInfo]

class ArticleStatus(BaseModel):
    id: str
    status: Literal["drafting", "drafted", "published"]
    text: Optional[str]
    created_at: str
    updated_at: str

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

def load_entities_data():
    """Load entities from file into memory"""
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

def load_drafts():
    """Load drafts from file into memory"""
    global drafts_store
    if os.path.exists(drafts_file):
        with file_lock(drafts_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        data = json.loads(line)
                        if 'id' in data:
                            drafts_store[data['id']] = data
                    except json.JSONDecodeError:
                        continue

def save_drafts():
    """Save all drafts to file with file locking"""
    with file_lock(drafts_file, 'w') as f:
        f.write("# Article drafts KV store - ID -> {type, statuses, results}\n")
        for draft in drafts_store.values():
            f.write(json.dumps(draft) + '\n')

def load_articles():
    """Load articles from file into memory"""
    global articles_store
    if os.path.exists(articles_file):
        with file_lock(articles_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        data = json.loads(line)
                        if 'id' in data:
                            articles_store[data['id']] = data
                    except json.JSONDecodeError:
                        continue

def save_articles():
    """Save all articles to file with file locking"""
    with file_lock(articles_file, 'w') as f:
        f.write("# Articles KV store - ID -> {status, text}\n")
        for article in articles_store.values():
            f.write(json.dumps(article) + '\n')

def save_entities_data():
    """Save entities data to file"""
    with open(entities_file, 'w') as f:
        f.write("# Simple key-value store for entities (JSON format)\n")
        for entity in entities_store.values():
            f.write(json.dumps(entity) + '\n')

def update_entity_status(entity_id: str, new_status: str):
    """Update entity status and save to file"""
    if entity_id in entities_store:
        entities_store[entity_id]['status'] = new_status
        save_entities_data()

def draft_exists(draft_id: str) -> bool:
    """Check if a draft exists"""
    return draft_id in drafts_store

def validate_notability(entity_id: str) -> bool:
    """Validate that entity exists in notability store with meets/exceeds status"""
    if not notability_exists(entity_id):
        return False
    
    notability_data = notability_store.get(entity_id)
    if not notability_data:
        return False
    
    status = notability_data.get('notability_status', '').lower()
    return status in ['meets', 'exceeds']

def extract_pages_content(results: Dict[str, Any]) -> Dict[str, str]:
    """Extract and format pages content from draft results for article generation"""
    section_content = {}
    
    # Map section names to variable names for the prompt
    section_mapping = {
        "early_life": "elac",  # early life and education
        "pre_vc_career": "pvcr",  # pre venture capitalist roles
        "vc_career": "vcc",  # venture capital career
        "notable_investments": "ni",  # notable investments
        "personal_life": "pl"  # personal life
    }
    
    for section, var_name in section_mapping.items():
        section_data = results.get(section, {})
        pages = section_data.get('pages', [])
        
        # Combine all page descriptions into a single text
        content_parts = []
        for page in pages:
            title = page.get('page_title', '')
            description = page.get('description', '')
            if description:
                content_parts.append(f"Source: {title}\n{description}")
        
        section_content[var_name] = '\n\n'.join(content_parts) if content_parts else ""
    
    return section_content

async def call_openai_prompt(prompt_id: str, prompt_version: str, entity_name: str, entity_context: str, entity_type: str) -> Dict[str, Any]:
    """Generic function to call OpenAI API with different prompts"""
    try:
        type_mapping = {
            "venture_capitalist": "Venture Capitalist",
            "startup_founder": "Startup Founder",
            "startup_company": "Startup Company",
            "venture_firm": "Venture Firm"
        }
        formatted_type = type_mapping.get(entity_type, entity_type)
        
        response = client.responses.create(
            prompt={
                "id": prompt_id,
                "version": prompt_version,
                "variables": {
                    "entity": entity_name,
                    "context": entity_context,
                    "type": formatted_type
                }
            },
            background=True
        )
        
        return {"job_id": response.id, "status": "pending"}
            
    except Exception as e:
        return {"pages": []}

async def create_vc_research_jobs(entity_id: str, entity_type: str) -> tuple[Dict[str, str], Dict[str, Any]]:
    """Create research jobs for venture capitalist sections"""
    entity_data = entities_store.get(entity_id)
    if not entity_data:
        raise ValueError(f"Entity {entity_id} not found in entities store")
    
    entity_name = entity_data.get('name', entity_id)
    entity_context = entity_data.get('context', '')
    
    section_prompts = {
        "early_life": (PROMPT_IDS["early_life"], "7"),
        "pre_vc_career": (PROMPT_IDS["pre_vc_career"], "3"),
        "vc_career": (PROMPT_IDS["vc_career"], "3"),
        "notable_investments": (PROMPT_IDS["notable_investments"], "3"),
        "personal_life": (PROMPT_IDS["personal_life"], "3")
    }
    
    job_ids = {}
    initial_results = {}
    
    for section, prompt_info in section_prompts.items():
        if prompt_info:
            prompt_id, version = prompt_info
            try:
                result = await call_openai_prompt(prompt_id, version, entity_name, entity_context, entity_type)
                openai_job_id = result.get("job_id")
                if openai_job_id:
                    job_ids[f"{section}_id"] = openai_job_id
                    initial_results[section] = None
                else:
                    fallback_job_id = f"{entity_id}_{section}_{uuid.uuid4().hex[:8]}"
                    job_ids[f"{section}_id"] = fallback_job_id
                    initial_results[section] = result
            except Exception as e:
                fallback_job_id = f"{entity_id}_{section}_{uuid.uuid4().hex[:8]}"
                job_ids[f"{section}_id"] = fallback_job_id
                initial_results[section] = None
        else:
            job_id = f"{entity_id}_{section}_{uuid.uuid4().hex[:8]}"
            job_ids[f"{section}_id"] = job_id
            initial_results[section] = None
    
    return job_ids, initial_results

async def create_article_draft(entity_id: str) -> str:
    """Create an article draft from completed research sections"""
    # Get entity data
    entity_data = entities_store.get(entity_id)
    if not entity_data:
        raise ValueError(f"Entity {entity_id} not found in entities store")
    
    # Get draft data
    draft_data = drafts_store.get(entity_id)
    if not draft_data:
        raise ValueError(f"Draft {entity_id} not found in drafts store")
    
    # Extract content from research results
    results = draft_data.get('results', {})
    section_content = extract_pages_content(results)
    
    entity_name = entity_data.get('name', entity_id)
    entity_context = entity_data.get('context', '')
    entity_type = draft_data.get('type', 'venture_capitalist')
    
    # Convert entity type to human readable format
    type_mapping = {
        "venture_capitalist": "Venture Capitalist",
        "startup_founder": "Startup Founder",
        "startup_company": "Startup Company",
        "venture_firm": "Venture Firm"
    }
    formatted_type = type_mapping.get(entity_type, entity_type)
    
    # Call OpenAI to generate the article
    response = client.responses.create(
        prompt={
            "id": ARTICLE_DRAFT_PROMPT_ID,
            "version": "5",
            "variables": {
                "entity": entity_name,
                "context": entity_context,
                "type": formatted_type,
                "elac": section_content.get("elac", ""),
                "pvcr": section_content.get("pvcr", ""),
                "vcc": section_content.get("vcc", ""),
                "ni": section_content.get("ni", ""),
                "pl": section_content.get("pl", "")
            }
        }
    )
    
    # Extract the JSON response containing markdown blocks
    if response.output and len(response.output) > 0:
        last_output = response.output[-1]
        if hasattr(last_output, 'content') and last_output.content:
            json_text = last_output.content[0].text
            # Return the JSON string (client will parse the markdown blocks)
            return json_text
    
    return ""

async def check_background_task_status(job_id: str) -> Optional[Dict[str, Any]]:
    """Check if a background task has completed and return its result"""
    try:
        response = client.responses.retrieve(job_id)
        
        if response.status == "completed":
            # Get the last item in the output array (the actual message response)
            if response.output and len(response.output) > 0:
                last_output = response.output[-1]
                if hasattr(last_output, 'content') and last_output.content:
                    text_content = last_output.content[0].text
                    return json.loads(text_content)
            return {"pages": []}
        else:
            return None
            
    except Exception as e:
        return None

async def update_draft_progress(draft_id: str) -> DraftProgressResponse:
    """Check all background tasks for a draft and update completed results"""
    if not draft_exists(draft_id):
        raise HTTPException(status_code=404, detail="Draft not found")
    
    draft_data = drafts_store[draft_id]
    statuses = draft_data.get('statuses', {})
    results = draft_data.get('results', {})
    
    updated_sections = []
    total_sections = len(statuses)
    
    # Check each background task
    for section_key, job_id in statuses.items():
        section_name = section_key.replace('_id', '')
        
        if job_id and results.get(section_name) is None:
            task_result = await check_background_task_status(job_id)
            if task_result is not None:
                results[section_name] = task_result
                updated_sections.append(section_name)
    
    # Count completed sections
    completed_sections = sum(1 for result in results.values() if result is not None)
    pending_sections = total_sections - completed_sections
    progress_percentage = (completed_sections / total_sections) * 100 if total_sections > 0 else 0
    is_complete = completed_sections == total_sections
    
    # Update the draft if any sections were updated
    if updated_sections:
        draft_data['results'] = results
        draft_data['updated_at'] = datetime.utcnow().isoformat()
        save_drafts()
    
    return DraftProgressResponse(
        id=draft_id,
        total_sections=total_sections,
        completed_sections=completed_sections,
        pending_sections=pending_sections,
        progress_percentage=progress_percentage,
        updated_sections=updated_sections,
        is_complete=is_complete
    )

@router.post("/", response_model=DraftStatus)
async def create_draft(request: CreateDraftRequest):
    """Create a new draft if entity meets notability requirements"""
    load_entities_data()
    load_drafts()
    
    if not validate_notability(request.id):
        raise HTTPException(
            status_code=400, 
            detail="Entity does not exist or does not meet notability requirements"
        )
    
    if draft_exists(request.id):
        raise HTTPException(
            status_code=409,
            detail="Draft already exists for this entity"
        )
    
    if request.type != "venture_capitalist":
        raise HTTPException(
            status_code=501,
            detail=f"Entity type '{request.type}' not yet implemented. Only 'venture_capitalist' is currently supported."
        )
    
    timestamp = datetime.utcnow().isoformat()
    
    if request.type == "venture_capitalist":
        try:
            job_ids, initial_results = await create_vc_research_jobs(request.id, request.type)
            statuses = job_ids
            results = initial_results
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error creating research jobs: {str(e)}")
    else:
        statuses = {}
        results = {}
    
    draft_data = {
        "id": request.id,
        "type": request.type,
        "statuses": statuses,
        "results": results,
        "created_at": timestamp,
        "updated_at": timestamp
    }
    
    drafts_store[request.id] = draft_data
    save_drafts()
    update_entity_status(request.id, 'drafting_sections')
    
    return DraftStatus(**draft_data)

@router.get("/{draft_id}", response_model=DraftStatus)
async def get_draft(draft_id: str):
    """Get a specific draft by ID"""
    # Reload data to ensure we have the latest state
    load_drafts()
    
    if not draft_exists(draft_id):
        raise HTTPException(status_code=404, detail="Draft not found")
    
    return DraftStatus(**drafts_store[draft_id])

@router.get("/", response_model=list[DraftStatus])
async def list_drafts():
    """List all drafts"""
    # Reload data to ensure we have the latest state
    load_drafts()
    
    return [DraftStatus(**draft) for draft in drafts_store.values()]

@router.get("/{draft_id}/check-progress", response_model=DraftProgressResponse)
async def check_draft_progress(draft_id: str):
    """Check progress of background tasks for a draft and update any completed results"""
    load_entities_data()
    load_drafts()
    return await update_draft_progress(draft_id)

@router.post("/{draft_id}/draft-document", response_model=ArticleStatus)
async def draft_document(draft_id: str):
    """Draft an article document from completed research sections (overwrites existing if present)"""
    load_entities_data()
    load_drafts()
    load_articles()
    
    # Check if draft exists
    if not draft_exists(draft_id):
        raise HTTPException(status_code=404, detail="Draft not found")
    
    timestamp = datetime.utcnow().isoformat()
    
    try:
        # Create the article draft
        article_text = await create_article_draft(draft_id)
        
        # Create or update article entry
        existing_article = articles_store.get(draft_id)
        article_data = {
            "id": draft_id,
            "status": "drafted",
            "text": article_text,
            "created_at": existing_article.get("created_at", timestamp) if existing_article else timestamp,
            "updated_at": timestamp
        }
        
        # Save to articles store (overwrites if exists)
        articles_store[draft_id] = article_data
        save_articles()
        
        # Update entity status
        update_entity_status(draft_id, 'drafted_sections')
        
        return ArticleStatus(**article_data)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating article draft: {str(e)}")

@router.get("/articles/{article_id}", response_model=ArticleStatus)
async def get_article(article_id: str):
    """Get a specific article by ID"""
    load_articles()
    
    if article_id not in articles_store:
        raise HTTPException(status_code=404, detail="Article not found")
    
    return ArticleStatus(**articles_store[article_id])

@router.get("/articles/", response_model=list[ArticleStatus])
async def list_articles():
    """List all articles"""
    load_articles()
    
    return [ArticleStatus(**article) for article in articles_store.values()]

# Load data on module import
load_entities_data()
load_drafts()
load_articles()