import google.generativeai as genai
from core.config import settings

if settings.gemini_api_key:
    genai.configure(api_key=settings.gemini_api_key)

# Placeholder string for now
def setup_llm():
    pass
