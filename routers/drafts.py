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
from .entities import entities_store, save_entities, load_entities

router = APIRouter(
    prefix="/drafts",
    tags=["drafts"],
    responses={404: {"description": "Not found"}},
)

# Initialize OpenAI client
client = OpenAI()

# Store for drafts and articles
drafts_store: Dict[str, dict] = {}
drafts_file = "data/drafts.txt"
articles_store: Dict[str, dict] = {}
articles_file = "data/articles.txt"

EntityType = Literal["venture_capitalist", "startup_founder", "startup_company", "venture_firm"]

# Prompt IDs and versions for different research sections
PROMPT_IDS = {
    "early_life": {"id": "pmpt_6881597633e08193a2ea8b886f8aa8990e7ece07212aea25", "version": "10"},
    "pre_vc_career": {"id": "pmpt_68816c05988c8193856a632187c8fe4d08d13066f2175710", "version": "6"},
    "vc_career": {"id": "pmpt_68816c254784819792b04926ab25312c0ae69cb869929a41", "version": "6"},
    "notable_investments": {"id": "pmpt_68816c4c78fc8190858a214948b257940b4a7c7d059861df", "version": "6"},
    "personal_life": {"id": "pmpt_68816c6a82a8819687e1eeda14f1a9480ae9ac0c76914685", "version": "6"}
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
    sections: Optional[Dict[str, Any]]
    job_ids: Optional[Dict[str, str]]  # Track background job IDs for each section
    created_at: str
    updated_at: str

class ArticleProgressResponse(BaseModel):
    id: str
    total_sections: int
    completed_sections: int
    pending_sections: int
    progress_percentage: float
    updated_sections: List[str]
    is_complete: bool

class UpdateArticleRequest(BaseModel):
    status: Optional[Literal["drafting", "drafted", "published"]] = None
    sections: Optional[Dict[str, Any]] = None

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

def update_entity_status(entity_id: str, new_status: str):
    """Update entity status and save to file"""
    if entity_id in entities_store:
        entities_store[entity_id]['status'] = new_status
        save_entities()

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
            # Handle new schema with exhaustive_description and mla_citation
            if 'exhaustive_description' in page and 'mla_citation' in page:
                description = page.get('exhaustive_description', '')
                citation = page.get('mla_citation', {})
                title = citation.get('page_title', '')
                if description:
                    content_parts.append(f"Source: {title}\n{description}")
            # Fallback to old schema for backward compatibility
            else:
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
        "early_life": (PROMPT_IDS["early_life"]["id"], PROMPT_IDS["early_life"]["version"]),
        "pre_vc_career": (PROMPT_IDS["pre_vc_career"]["id"], PROMPT_IDS["pre_vc_career"]["version"]),
        "vc_career": (PROMPT_IDS["vc_career"]["id"], PROMPT_IDS["vc_career"]["version"]),
        "notable_investments": (PROMPT_IDS["notable_investments"]["id"], PROMPT_IDS["notable_investments"]["version"]),
        "personal_life": (PROMPT_IDS["personal_life"]["id"], PROMPT_IDS["personal_life"]["version"])
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

async def create_article_drafting_jobs(entity_id: str, all_pages_str: str, entity_name: str, entity_context: str) -> tuple[Dict[str, str], Dict[str, Any]]:
    """Create article drafting jobs for all sections"""
    
    # Section mapping for the API calls
    section_mapping = {
        "early_life": "Early Life",
        "career": "Career", 
        "notable_investments": "Notable Investments"
    }
    
    job_ids = {}
    initial_results = {}
    
    # Process each section
    for section_key, section_name in section_mapping.items():
        try:
            # Use different endpoint for notable_investments
            if section_key == "notable_investments":
                # Call special notable investments endpoint
                response = client.responses.create(
                    prompt={
                        "id": "pmpt_6883c4eb15f481949785358f13d37243075c7030141d46f3",
                        "version": "7",
                        "variables": {
                            "entity": entity_name,
                            "context": entity_context,
                            "type": "Venture Capitalist",
                            "sources": all_pages_str
                        }
                    },
                    background=True
                )
            else:
                # Call generic encyclopedia section endpoint
                response = client.responses.create(
                    prompt={
                        "id": "pmpt_6883c4dcfe5c819387acad8910d66c340a50e18e12e625a6",
                        "version": "6",
                        "variables": {
                            "entity": entity_name,
                            "context": entity_context,
                            "type": "Venture Capitalist",
                            "section": section_name,
                            "sources": all_pages_str
                        }
                    },
                    input=[],
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "encyclopedia_section_blocks",
                            "strict": True,
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "blocks": {
                                        "type": "array",
                                        "description": "A list of content blocks that make up the encyclopedia section. These can be headings, subheadings, paragraphs, etc.",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "type": {
                                                    "type": "string",
                                                    "enum": [
                                                        "heading",
                                                        "subheading",
                                                        "paragraph",
                                                        "quote",
                                                        "list"
                                                    ],
                                                    "description": "The type of content block. Determines how the block is rendered."
                                                },
                                                "content": {
                                                    "type": "string",
                                                    "description": "The textual content of the block."
                                                },
                                                "citations": {
                                                    "type": "array",
                                                    "description": "Optional in-line citations within this block, referencing the reference list by ID.",
                                                    "items": {
                                                        "type": "object",
                                                        "properties": {
                                                            "id": {
                                                                "type": "integer",
                                                                "description": "The ID of the source being cited, corresponding to the references list."
                                                            }
                                                        },
                                                        "required": [
                                                            "id"
                                                        ],
                                                        "additionalProperties": False
                                                    }
                                                }
                                            },
                                            "required": [
                                                "type",
                                                "content",
                                                "citations"
                                            ],
                                            "additionalProperties": False
                                        }
                                    },
                                    "references": {
                                        "type": "array",
                                        "description": "The list of sources used in citations throughout this section.",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "id": {
                                                    "type": "integer",
                                                    "description": "A unique identifier for the citation, used in the citations array."
                                                },
                                                "title": {
                                                    "type": "string",
                                                    "description": "The title of the article or source."
                                                },
                                                "url": {
                                                    "type": "string",
                                                    "description": "The full URL of the source."
                                                },
                                                "author": {
                                                    "type": "string",
                                                    "description": "The name of the author or creator of the source."
                                                },
                                                "publisher": {
                                                    "type": "string",
                                                    "description": "The publisher or platform where the source was published."
                                                },
                                                "date": {
                                                    "type": "string",
                                                    "description": "The date the source was published in YYYY-MM-DD format."
                                                }
                                            },
                                            "required": [
                                                "id",
                                                "title",
                                                "url",
                                                "author",
                                                "publisher",
                                                "date"
                                            ],
                                            "additionalProperties": False
                                        }
                                    }
                                },
                                "required": [
                                    "blocks",
                                    "references"
                                ],
                                "additionalProperties": False
                            }
                        }
                    },
                    reasoning={},
                    max_output_tokens=5000,
                    store=True,
                    background=True
                )
            
            job_ids[f"{section_key}_id"] = response.id
            initial_results[section_key] = None
            
        except Exception as e:
            print(f"Error creating job for section {section_key}: {e}")
            fallback_job_id = f"{entity_id}_{section_key}_{uuid.uuid4().hex[:8]}"
            job_ids[f"{section_key}_id"] = fallback_job_id
            initial_results[section_key] = None
    
    # Create personal life job
    try:
        personal_life_response = client.responses.create(
            prompt={
                "id": "pmpt_688555fe690c8190a80f494f1960150606270da2f1dfcb3f",
                "version": "2",
                "variables": {
                    "entity": entity_name,
                    "context": entity_context,
                    "type": "Venture Capitalist",
                    "sources": all_pages_str,
                    "early_life": ""  # Will be updated when early_life completes
                }
            },
            background=True
        )
        job_ids["personal_life_id"] = personal_life_response.id
        initial_results["personal_life"] = None
    except Exception as e:
        print(f"Error creating personal life job: {e}")
        fallback_job_id = f"{entity_id}_personal_life_{uuid.uuid4().hex[:8]}"
        job_ids["personal_life_id"] = fallback_job_id
        initial_results["personal_life"] = None
    
    # Create person infobox job
    try:
        person_infobox_response = client.responses.create(
            prompt={
                "id": "pmpt_6883c991fe888196a6ae9fc79bbd07880738447170486610",
                "version": "3",
                "variables": {
                    "entity": entity_name,
                    "context": entity_context,
                    "type": "Venture Capitalist",
                    "sources": all_pages_str
                }
            },
            background=True
        )
        job_ids["person_infobox_id"] = person_infobox_response.id
        initial_results["person_infobox"] = None
    except Exception as e:
        print(f"Error creating person infobox job: {e}")
        fallback_job_id = f"{entity_id}_person_infobox_{uuid.uuid4().hex[:8]}"
        job_ids["person_infobox_id"] = fallback_job_id
        initial_results["person_infobox"] = None
    
    # Create lead section job
    try:
        lead_response = client.responses.create(
            prompt={
                "id": "pmpt_68842015293c819483d326d4693478e10e0fc773bb2e0e5d",
                "version": "3",
                "variables": {
                    "entity": entity_name,
                    "context": entity_context,
                    "type": "Venture Capitalist",
                    "sources": all_pages_str
                }
            },
            background=True
        )
        job_ids["lead_id"] = lead_response.id
        initial_results["lead"] = None
    except Exception as e:
        print(f"Error creating lead job: {e}")
        fallback_job_id = f"{entity_id}_lead_{uuid.uuid4().hex[:8]}"
        job_ids["lead_id"] = fallback_job_id
        initial_results["lead"] = None
    
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

async def update_article_progress(article_id: str) -> ArticleProgressResponse:
    """Check all background tasks for an article and update completed results"""
    if article_id not in articles_store:
        raise HTTPException(status_code=404, detail="Article not found")
    
    article_data = articles_store[article_id]
    job_ids = article_data.get('job_ids', {})
    sections = article_data.get('sections', {})
    
    updated_sections = []
    total_sections = len(job_ids)
    
    # Check each background task
    for job_key, job_id in job_ids.items():
        section_name = job_key.replace('_id', '')
        
        if job_id and sections.get(section_name) is None:
            task_result = await check_background_task_status(job_id)
            if task_result is not None:
                sections[section_name] = task_result
                updated_sections.append(section_name)
    
    # Count completed sections
    completed_sections = sum(1 for section in sections.values() if section is not None)
    pending_sections = total_sections - completed_sections
    progress_percentage = (completed_sections / total_sections) * 100 if total_sections > 0 else 0
    is_complete = completed_sections == total_sections
    
    # Update the article if any sections were updated
    if updated_sections:
        article_data['sections'] = sections
        article_data['updated_at'] = datetime.utcnow().isoformat()
        
        # Update status to "drafted" if all sections are complete
        if is_complete:
            article_data['status'] = 'drafted'
            update_entity_status(article_id, 'drafted_article')
        
        save_articles()
    
    return ArticleProgressResponse(
        id=article_id,
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
    load_entities()
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
    update_entity_status(request.id, 'drafting_article')
    
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
    load_entities()
    load_drafts()
    return await update_draft_progress(draft_id)

@router.post("/{draft_id}/draft-document", response_model=ArticleStatus)
async def draft_document(draft_id: str):
    """Start article drafting process with background jobs"""
    load_entities()
    load_drafts()
    load_articles()
    
    # Check if draft exists
    if not draft_exists(draft_id):
        raise HTTPException(status_code=404, detail="Draft not found")
    
    # Get entity data
    entity_data = entities_store.get(draft_id)
    if not entity_data:
        raise HTTPException(status_code=404, detail="Entity not found")
    
    # Get draft data with completed research results
    draft_data = drafts_store.get(draft_id)
    if not draft_data:
        raise HTTPException(status_code=404, detail="Draft data not found")
    
    results = draft_data.get('results', {})
    if not results:
        raise HTTPException(status_code=400, detail="No research results found")
    
    timestamp = datetime.utcnow().isoformat()
    
    try:
        entity_name = entity_data.get('name', draft_id)
        entity_context = entity_data.get('context', '')
        
        # Helper function to get all sources from all research tasks
        def get_all_research_pages():
            all_pages = []
            
            # Research sections to combine
            research_sections = ['early_life', 'pre_vc_career', 'vc_career', 'notable_investments', 'personal_life']
            
            for section_key in research_sections:
                section_result = results.get(section_key, {})
                if 'pages' in section_result:
                    all_pages.extend(section_result['pages'])
            
            return all_pages
        
        # Get all pages from all research tasks
        all_research_pages = get_all_research_pages()
        all_pages_str = json.dumps(all_research_pages)
        
        # Create background jobs for all article sections
        job_ids, initial_sections = await create_article_drafting_jobs(draft_id, all_pages_str, entity_name, entity_context)
        
        # Create or update article entry
        existing_article = articles_store.get(draft_id)
        article_data = {
            "id": draft_id,
            "status": "drafting",
            "sections": initial_sections,
            "job_ids": job_ids,
            "created_at": existing_article.get("created_at", timestamp) if existing_article else timestamp,
            "updated_at": timestamp
        }
        
        # Save to articles store (overwrites if exists)
        articles_store[draft_id] = article_data
        save_articles()
        
        # Update entity status
        update_entity_status(draft_id, 'drafting_article')
        
        return ArticleStatus(**article_data)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating article drafting jobs: {str(e)}")

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

@router.put("/articles/{article_id}", response_model=ArticleStatus)
async def update_article(article_id: str, request: UpdateArticleRequest):
    """Update a specific article by ID"""
    load_articles()
    
    if article_id not in articles_store:
        raise HTTPException(status_code=404, detail="Article not found")
    
    # Get existing article data
    existing_article = articles_store[article_id]
    
    # Update only the fields that are provided
    if request.status is not None:
        existing_article["status"] = request.status
    
    if request.sections is not None:
        existing_article["sections"] = request.sections
    
    # Update the timestamp
    existing_article["updated_at"] = datetime.utcnow().isoformat()
    
    # Save the updated article
    articles_store[article_id] = existing_article
    save_articles()
    
    return ArticleStatus(**existing_article)

@router.get("/articles/{article_id}/check-progress", response_model=ArticleProgressResponse)
async def check_article_progress(article_id: str):
    """Check progress of background tasks for an article and update any completed results"""
    load_articles()
    return await update_article_progress(article_id)

# Load data on module import
load_entities()
load_drafts()
load_articles()