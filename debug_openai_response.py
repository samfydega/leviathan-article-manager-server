#!/usr/bin/env python3
"""
Debug script for OpenAI background responses.
Usage: python debug_openai_response.py <response_id>
"""

import sys
import json
import os
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables from .env file
load_dotenv()

def debug_openai_response(response_id):
    """Retrieve and debug an OpenAI background response"""
    
    # Initialize OpenAI client
    client = OpenAI()
    
    try:
        print(f"[DEBUG] Retrieving response for ID: {response_id}")
        
        # Retrieve the response from OpenAI
        response = client.responses.retrieve(response_id)
        
        print(f"[DEBUG] Response status: {response.status}")
        print(f"[DEBUG] Response ID: {response.id}")
        print(f"[DEBUG] Response object type: {type(response)}")
        print(f"[DEBUG] Response object attributes: {dir(response)}")
        
        # Print the full response object
        print(f"\n[DEBUG] Full response object:")
        print(json.dumps(response.model_dump(), indent=2, default=str))
        
        # If completed, try to extract content
        if response.status == 'completed':
            print(f"\n[DEBUG] Attempting to extract content from completed response...")
            
            content = None
            if hasattr(response, 'output') and response.output:
                print(f"[DEBUG] Response has output with {len(response.output)} items")
                
                # Look for the last message in output that contains the JSON
                for i, item in enumerate(reversed(response.output)):
                    print(f"[DEBUG] Processing output item {len(response.output) - i - 1}: {type(item)}")
                    print(f"[DEBUG] Item attributes: {dir(item)}")
                    
                    if hasattr(item, 'content') and item.content:
                        print(f"[DEBUG] Item has content with {len(item.content)} items")
                        
                        for j, content_item in enumerate(item.content):
                            print(f"[DEBUG] Processing content item {j}: {type(content_item)}")
                            print(f"[DEBUG] Content item attributes: {dir(content_item)}")
                            
                            if hasattr(content_item, 'text'):
                                content = content_item.text
                                print(f"[DEBUG] Found text content: {content[:200]}...")
                                break
                        
                        if content:
                            break
            else:
                print(f"[DEBUG] Response has no output attribute or output is empty")
            
            if content:
                print(f"\n[DEBUG] Extracted content:")
                print(content)
                
                # Try to parse as JSON
                try:
                    parsed_content = json.loads(content)
                    print(f"\n[DEBUG] Parsed JSON content:")
                    print(json.dumps(parsed_content, indent=2))
                except json.JSONDecodeError as e:
                    print(f"[DEBUG] Content is not valid JSON: {e}")
            else:
                print(f"[DEBUG] Could not extract content from response")
        
        elif response.status == 'failed':
            print(f"[DEBUG] Response failed - check error details above")
        else:
            print(f"[DEBUG] Response is still pending/processing")
            
    except Exception as e:
        print(f"[ERROR] Exception occurred: {str(e)}")
        print(f"[ERROR] Exception type: {type(e)}")
        import traceback
        print(f"[ERROR] Traceback: {traceback.format_exc()}")

def main():
    if len(sys.argv) != 2:
        print("Usage: python debug_openai_response.py <response_id>")
        print("Example: python debug_openai_response.py resp_6883bc604ad0819a94ac84e445bc74c70e2b5963dc91916d")
        sys.exit(1)
    
    response_id = sys.argv[1]
    debug_openai_response(response_id)

if __name__ == "__main__":
    main() 