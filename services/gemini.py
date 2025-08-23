import httpx
import logging
import json
from typing import List, Optional, AsyncGenerator
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
            self.logger.info(f"Sending non-streaming request to Gemini: {text[:50]}...")
            response = await client.post(url, json=payload, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            content = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            self.logger.info(f"Received Gemini response: {content[:50]}...")
            return content

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
            self.logger.info(f"Sending history request to Gemini: {len(history)} messages")
            response = await client.post(url, json=payload, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            content = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            self.logger.info(f"Received Gemini response: {content[:50]}...")
            return content

    async def generate_streaming_content(self, text: str) -> AsyncGenerator[str, None]:
        if not self.api_key:
            raise RuntimeError("Gemini API key not set")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:streamGenerateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 2048
            }
        }

        async with httpx.AsyncClient() as client:
            self.logger.info(f"Sending streaming request to Gemini: {text[:50]}...")
            async with client.stream("POST", url, json=payload, timeout=120.0) as response:
                try:
                    response.raise_for_status()
                    buffer = ""
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        self.logger.debug(f"Raw Gemini response line: {line}")
                        if line.startswith("data: "):
                            line = line[6:]
                        buffer += line
                        try:
                            data = json.loads(buffer)
                            if isinstance(data, list):
                                data = data[0] if data else {}
                            content = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                            if content:
                                self.logger.info(f"Yielding Gemini chunk: {content[:50]}...")
                                yield content
                                buffer = ""
                            else:
                                self.logger.debug("No text content in response, continuing")
                                continue
                        except json.JSONDecodeError:
                            self.logger.debug("Partial JSON, continuing to accumulate")
                            continue
                        except Exception as e:
                            self.logger.error(f"Unexpected error parsing Gemini response: {e}, buffer: {buffer}")
                            buffer = ""
                            continue
                except httpx.HTTPStatusError as e:
                    self.logger.error(f"Gemini streaming error: {e}, response: {e.response.text}")
                    raise
                except Exception as e:
                    self.logger.error(f"Unexpected error in Gemini streaming: {e}")
                    raise