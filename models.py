from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Union
from enum import Enum
import time

# NER Models
class Entity(BaseModel):
    type: str
    value: str

class NERRequest(BaseModel):
    text: str

class NERResponse(BaseModel):
    entities: List[Entity]

# Entity Store Models
class EntityStatus(str, Enum):
    ignored = "ignored"
    backlogged = "backlogged"
    notability = "notability"

class EntityPhase(str, Enum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"

class EntityStatusObject(BaseModel):
    state: Optional[EntityStatus] = Field(None, description="Current state of the entity")
    phase: Optional[EntityPhase] = Field(None, description="Current phase of processing")

class CreateEntityRequest(BaseModel):
    entity_name: str = Field(..., description="The name of the entity (e.g., 'Palm City, FL')")
    entity_context: str = Field(..., description="Context or description of the entity")
    entity_type: str = Field(..., description="Type of entity (e.g., 'PERSON', 'ORG', 'GPE')")
    status: EntityStatusObject = Field(..., description="Status object with state and phase")

class UpdateEntityStatusRequest(BaseModel):
    status: EntityStatusObject = Field(..., description="New status object for the entity")

class EntityResponse(BaseModel):
    id: str = Field(..., description="Generated ID from entity name (e.g., 'palm-city-fl')")
    name: str = Field(..., description="Original entity name")
    context: str = Field(..., description="Entity context or description")
    entity_type: str = Field(..., description="Type of entity (e.g., 'PERSON', 'ORG', 'GPE')")
    status: Optional[EntityStatusObject] = Field(None, description="Current status with state and phase")

class DraftedEntityResponse(BaseModel):
    id: str = Field(..., description="Generated ID from entity name (e.g., 'palm-city-fl')")
    name: str = Field(..., description="Original entity name")
    context: str = Field(..., description="Entity context or description")
    entity_type: str = Field(..., description="Type of entity (e.g., 'PERSON', 'ORG', 'GPE')")
    status: Optional[EntityStatusObject] = Field(None, description="Current status with state and phase")
    article_text: Optional[str] = Field(None, description="Article content as JSON string of markdown blocks")

class EntitiesListResponse(BaseModel):
    entities: List[EntityResponse] = Field(default=[], description="List of all entities")

# Notability Store Models
class Source(BaseModel):
    url: str = Field(..., description="The URL of the source, as an absolute string")
    page_title: str = Field(..., min_length=1, description="The title of the page or article")
    meets_standards: bool = Field(..., description="Whether the source meets the notability standards")
    explanation: str = Field(..., description="Explanation of why the source does or doesn't meet standards")

class NotabilityEntityResponse(BaseModel):
    id: str = Field(..., description="Generated ID from entity name")
    name: str = Field(..., description="Original entity name")
    context: str = Field(..., description="Entity context or description")
    entity_type: str = Field(..., description="Type of entity (e.g., 'PERSON', 'ORG', 'GPE')")
    status: Optional[EntityStatusObject] = Field(None, description="Current status with state and phase")
    notability_status: Optional[str] = Field(None, description="Notability evaluation result (exceeds, meets, fails, null)")
    notability_rationale: Optional[str] = Field(None, description="Rationale for notability evaluation")
    sources: List[Source] = Field(default=[], description="Array of evaluated sources")

class NotabilityData(BaseModel):
    id: str = Field(..., description="Entity ID (matches data/entities.txt)")
    notability_status: Optional[str] = Field(None, description="Notability evaluation result (exceeds, meets, fails, null)")
    openai_research_request_id: Optional[str] = Field(None, description="OpenAI research request ID")
    research_request_timestamp: Optional[float] = Field(None, description="Unix timestamp when research request was made")
    sources: List[Source] = Field(default=[], description="Array of evaluated sources")
    openai_notability_request_id: Optional[str] = Field(None, description="OpenAI notability request ID")
    notability_request_timestamp: Optional[float] = Field(None, description="Unix timestamp when notability request was made")
    notability_rationale: Optional[str] = Field(None, description="Rationale for notability evaluation")
    retry_count: int = Field(default=0, description="Number of times this request has been retried due to timeout")

class CreateNotabilityRequest(BaseModel):
    # No fields needed - the entity ID will come from the URL path parameter
    pass

class ResearchRequest(BaseModel):
    id: str = Field(..., description="Entity ID to research")

class ResearchResponse(BaseModel):
    openai_research_request_id: str = Field(..., description="OpenAI research request ID")

class ResearchStatusRequest(BaseModel):
    id: str = Field(..., description="Entity ID to check research status for")

class ResearchStatusResponse(BaseModel):
    status: str = Field(..., description="Status of the research request (pending, completed, failed)")
    openai_research_request_id: Optional[str] = Field(None, description="OpenAI research request ID")
    sources: Optional[List[Source]] = Field(None, description="Parsed sources if completed")

class NotabilityStatusRequest(BaseModel):
    id: str = Field(..., description="Entity ID to check notability status for")

class NotabilityStatusResponse(BaseModel):
    status: str = Field(..., description="Status of the notability request (pending, completed, failed)")
    openai_notability_request_id: Optional[str] = Field(None, description="OpenAI notability request ID")
    notability_status: Optional[str] = Field(None, description="Notability evaluation result (exceeds, meets, fails)")
    notability_rationale: Optional[str] = Field(None, description="Rationale for the notability evaluation")

# Basic API Response Models
class HealthResponse(BaseModel):
    status: str = Field(default="healthy", description="API health status")

class HelloResponse(BaseModel):
    Hello: str = Field(default="World", description="Hello world message")

# Constants for timeout handling
TIMEOUT_SECONDS = 600  # 10 minutes
MAX_RETRIES = 2  # Maximum number of retries before marking as failed 