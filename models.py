from pydantic import BaseModel, Field
from typing import List, Literal
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
    delete = "delete"
    backlog = "backlog"
    queue = "queue"
    processed = "processed"

class CreateEntityRequest(BaseModel):
    entity_name: str = Field(..., description="The name of the entity (e.g., 'Palm City, FL')")
    entity_context: str = Field(..., description="Context or description of the entity")
    status: EntityStatus = Field(..., description="Status of the entity processing")

class EntityResponse(BaseModel):
    id: str = Field(..., description="Generated ID from entity name (e.g., 'palm-city-fl')")
    name: str = Field(..., description="Original entity name")
    context: str = Field(..., description="Entity context or description")
    status: EntityStatus = Field(..., description="Current processing status")

class EntitiesListResponse(BaseModel):
    entities: List[EntityResponse] = Field(default=[], description="List of all entities")

# Basic API Response Models
class HealthResponse(BaseModel):
    status: str = Field(default="healthy", description="API health status")

class HelloResponse(BaseModel):
    Hello: str = Field(default="World", description="Hello world message") 