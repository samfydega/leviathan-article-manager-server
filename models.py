from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Union
from enum import Enum

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
    ignore = "ignore"
    backlog = "backlog"
    queue = "queue"
    researching = "researching"
    researched = "researched"

class CreateEntityRequest(BaseModel):
    entity_name: str = Field(..., description="The name of the entity (e.g., 'Palm City, FL')")
    entity_context: str = Field(..., description="Context or description of the entity")
    status: EntityStatus = Field(..., description="Status of the entity processing")

class UpdateEntityStatusRequest(BaseModel):
    status: EntityStatus = Field(..., description="New status for the entity")

class EntityResponse(BaseModel):
    id: str = Field(..., description="Generated ID from entity name (e.g., 'palm-city-fl')")
    name: str = Field(..., description="Original entity name")
    context: str = Field(..., description="Entity context or description")
    status: EntityStatus = Field(..., description="Current processing status")

class EntitiesListResponse(BaseModel):
    entities: List[EntityResponse] = Field(default=[], description="List of all entities")

# Notability Store Models
class SourceProximity(str, Enum):
    primary = "primary"
    secondary = "secondary"
    tertiary = "tertiary"

class SourceIndependence(str, Enum):
    THIRD_PARTY = "THIRD_PARTY"
    AFFILIATED = "AFFILIATED"
    SELF_PUBLISHED = "SELF_PUBLISHED"

class SourceReliability(str, Enum):
    PEER_REVIEWED = "PEER_REVIEWED"
    HIGH_QUALITY = "HIGH_QUALITY"
    MIXED = "MIXED"
    QUESTIONABLE = "QUESTIONABLE"
    UNRELIABLE = "UNRELIABLE"

class SourceDepth(str, Enum):
    SUBSTANTIAL = "SUBSTANTIAL"
    ROUTINE = "ROUTINE"
    MINIMAL = "MINIMAL"

class Source(BaseModel):
    url: str = Field(..., description="The URL of the source, as an absolute string")
    page_title: str = Field(..., min_length=1, description="The title of the page or article")
    publish_date: str = Field(..., min_length=1, description="Publication date in ISO 8601 format (YYYY-MM-DD)")
    proximity: SourceProximity = Field(..., description="How directly the source is tied to the subject")
    independence: SourceIndependence = Field(..., description="Independence of the outlet from the subject")
    reliability: SourceReliability = Field(..., description="Editorial reliability and standards")
    depth: SourceDepth = Field(..., description="Coverage depth of the source")

class ResearchedEntityResponse(BaseModel):
    id: str = Field(..., description="Generated ID from entity name")
    name: str = Field(..., description="Original entity name")
    context: str = Field(..., description="Entity context or description")
    status: EntityStatus = Field(..., description="Current processing status")
    notability_status: Optional[str] = Field(None, description="Notability evaluation result (exceeds, meets, fails, null)")
    notability_rationale: Optional[str] = Field(None, description="Rationale for notability evaluation")
    sources: List[Source] = Field(default=[], description="Array of evaluated sources")

class NotabilityData(BaseModel):
    id: str = Field(..., description="Entity ID (matches entities.txt)")
    notability_status: Optional[str] = Field(None, description="Notability evaluation result (exceeds, meets, fails, null)")
    openai_research_request_id: Optional[str] = Field(None, description="OpenAI research request ID")
    sources: List[Source] = Field(default=[], description="Array of evaluated sources")
    openai_notability_request_id: Optional[str] = Field(None, description="OpenAI notability request ID")
    notability_rationale: Optional[str] = Field(None, description="Rationale for notability evaluation")

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