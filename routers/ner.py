from fastapi import APIRouter, HTTPException
from openai import OpenAI
import json
import os
from dotenv import load_dotenv
from models import Entity, NERRequest, NERResponse
from routers.entities import format_entity_key, entity_exists

# Load environment variables
load_dotenv()

# Create router for NER endpoints
router = APIRouter(
    prefix="/ner",
    tags=["ner"],
    responses={500: {"description": "Internal server error"}},
)

# Initialize OpenAI client
client = OpenAI()

@router.post("/", response_model=NERResponse)
async def named_entity_recognition(request: NERRequest):
    """Perform Named Entity Recognition on the provided text using OpenAI prompt"""
    
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

        # Define entity types to filter out - focus on meaningful entities for companies and persons
        filtered_out_types = {
            "LANGUAGE",
            "DATE", 
            "TIME",
            "PERCENT",
            "MONEY",
            "QUANTITY", 
            "ORDINAL",
            "CARDINAL"
        }
        
        entities = []
        
        # Check if we have valid entities data
        if isinstance(entities_data, dict) and "entities" in entities_data and isinstance(entities_data["entities"], list):
            for entity_data in entities_data["entities"]:
                if isinstance(entity_data, dict) and "type" in entity_data and "value" in entity_data:
                    entity_type = entity_data["type"]
                    entity_value = entity_data["value"]
                    
                    # Filter out unwanted entity types - keep only meaningful entities like PERSON, ORG, etc.
                    if entity_type not in filtered_out_types:
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
        raise HTTPException(status_code=500, detail=f"Error processing NER request: {str(e)}") 