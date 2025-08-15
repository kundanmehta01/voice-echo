import httpx
import logging
from typing import List, Optional
from pydantic import BaseModel

class ChatMessage(BaseModel):
    role: str
    content: str

class GeminiService:
    def __init__(self, api_key: Optional[str]):
        self.api_key = api_key
        self.logger = logging.getLogger(__name__)

    async def generate_content(self, text: str) -> str:
        if not self.api_key:
            raise RuntimeError("Gemini API key not set")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"
        payload = {"contents": [{"parts": [{"text": text}]}]}

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            return data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")

    async def generate_content_with_history(self, history: List[ChatMessage]) -> str:
        if not self.api_key:
            raise RuntimeError("Gemini API key not set")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"
        payload = {
            "contents": [
                {
                    "role": "user" if msg.role == "user" else "model",
                    "parts": [{"text": msg.content}]
                } for msg in history
            ]
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            return data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")