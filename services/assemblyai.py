import os
import aiofiles
import httpx
import asyncio
import logging
from typing import Optional

class AssemblyAIService:
    def __init__(self, api_key: Optional[str]):
        self.api_key = api_key
        self.logger = logging.getLogger(__name__)

    async def upload_audio(self, file_path: str) -> str:
        if not self.api_key:
            raise RuntimeError("AssemblyAI API key not set")

        headers = {"authorization": self.api_key}
        async with aiofiles.open(file_path, "rb") as f:
            content = await f.read()

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.assemblyai.com/v2/upload",
                headers=headers,
                content=content,
                timeout=60.0
            )
            resp.raise_for_status()
            data = resp.json()
            upload_url = data.get("upload_url")
            if not upload_url:
                raise RuntimeError("AssemblyAI upload did not return upload_url")
            return upload_url

    async def create_and_wait_transcript(self, audio_url: str, max_attempts: int = 30, poll_interval: float = 2.0) -> str:
        if not self.api_key:
            raise RuntimeError("AssemblyAI API key not set")

        headers = {"authorization": self.api_key, "content-type": "application/json"}
        async with httpx.AsyncClient() as client:
            create = await client.post(
                "https://api.assemblyai.com/v2/transcript",
                json={"audio_url": audio_url},
                headers=headers,
                timeout=60.0
            )
            create.raise_for_status()
            transcript_id = create.json().get("id")
            if not transcript_id:
                raise RuntimeError("AssemblyAI did not return transcript id")

            for attempt in range(max_attempts):
                status_resp = await client.get(
                    f"https://api.assemblyai.com/v2/transcript/{transcript_id}",
                    headers=headers,
                    timeout=30.0
                )
                status_resp.raise_for_status()
                result = status_resp.json()
                status = result.get("status")
                self.logger.info(f"AssemblyAI status ({transcript_id}): {status} (attempt {attempt + 1})")
                if status == "completed":
                    return result.get("text", "")
                if status == "error":
                    raise RuntimeError(result.get("error", "AssemblyAI returned error"))
                await asyncio.sleep(poll_interval)

            raise TimeoutError("Transcription timed out")

    async def transcribe_audio(self, file_path: str) -> str:
        audio_url = await self.upload_audio(file_path)
        self.logger.info(f"Uploaded audio to AssemblyAI: {audio_url}")
        return await self.create_and_wait_transcript(audio_url)

    async def cleanup(self, file_path: Optional[str]):
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            self.logger.warning(f"Failed to remove {file_path}: {e}")