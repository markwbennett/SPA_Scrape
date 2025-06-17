#!/usr/bin/env python3
"""
Demo script to test Claude PDF analysis functionality
"""

import os
import base64
from dotenv import load_dotenv
import anthropic

# Load environment variables
load_dotenv()

def test_claude_pdf_analysis():
    """Test Claude analysis with a sample PDF"""
    
    # Check for API key
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        print("❌ ANTHROPIC_API_KEY not found in .env file")
        print("Please copy sample.env to .env and add your API key")
        return
    
    # Look for any PDF file in the briefs directory
    briefs_dir = "data/briefs"
    if not os.path.exists(briefs_dir):
        print(f"❌ No briefs directory found at {briefs_dir}")
        print("Run the main scraper first to download some briefs")
        return
    
    pdf_files = [f for f in os.listdir(briefs_dir) if f.endswith('.pdf')]
    if not pdf_files:
        print(f"❌ No PDF files found in {briefs_dir}")
        print("Run the main scraper first to download some briefs")
        return
    
    # Use the first PDF file found
    test_pdf = os.path.join(briefs_dir, pdf_files[0])
    print(f"🔍 Testing Claude analysis with: {test_pdf}")
    
    try:
        client = anthropic.Anthropic(api_key=api_key)
        
        # Read and encode PDF
        with open(test_pdf, 'rb') as f:
            pdf_content = base64.b64encode(f.read()).decode('utf-8')
        
        print("📤 Sending PDF to Claude...")
        
        # Send to Claude
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_content
                            }
                        },
                        {
                            "type": "text",
                            "text": """Please analyze this legal brief and identify the main legal issues being argued. 

Provide a concise list of the primary legal issues/arguments, categorized by area of law (e.g., "Fourth Amendment - Search and Seizure", "Sufficiency of Evidence", etc.).

Format your response as a simple list, one issue per line, like:
- Fourth Amendment - Warrantless search of vehicle
- Sufficiency of Evidence - Insufficient evidence of intent

Focus on the substantive legal arguments rather than procedural matters."""
                        }
                    ]
                }
            ]
        )
        
        print("✅ Claude analysis complete!")
        print("\n📋 Legal Issues Identified:")
        print("=" * 50)
        print(message.content[0].text)
        
    except Exception as e:
        print(f"❌ Error during Claude analysis: {e}")

if __name__ == "__main__":
    test_claude_pdf_analysis() 