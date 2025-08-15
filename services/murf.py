import os
import aiofiles
import httpx
import logging
from typing import List, Optional

class MurfService:
    def __init__(self, api_key: Optional[str]):
        self.api_key = api_key
        self.logger = logging.getLogger(__name__)

    async def generate_speech(self, text: str, filename: str, output_dir: str) -> str:
        if not self.api_key:
            raise RuntimeError("Murf API key not set")

        headers = {"api-key": self.api_key, "Content-Type": "application/json"}
        payload = {
            "text": text,
            "voiceId": "en-US-natalie",
            "style": "Conversational",
            "format": "mp3"
        }

        async with httpx.AsyncClient() as client:
            self.logger.info("Sending to Murf API")
            response = await client.post(
                "https://api.murf.ai/v1/speech/generate",
                json=payload,
                headers=headers,
                timeout=60.0
            )
            response.raise_for_status()
            data = response.json()
            audio_url = data.get("audioFile")
            if not audio_url:
                raise RuntimeError("Failed to get audio URL from Murf AI")

            audio_resp = await client.get(audio_url, timeout=60.0)
            audio_resp.raise_for_status()

            murf_filename = f"murf_{filename.replace('.webm', '.mp3')}"
            murf_file_path = os.path.join(output_dir, murf_filename)
            async with aiofiles.open(murf_file_path, "wb") as f_out:
                await f_out.write(audio_resp.content)
            return f"/Uploads/{murf_filename}"

    async def generate_speech_chunks(self, text: str, filename: str, output_dir: str) -> List[str]:
        def split_text(text: str, max_length: int = 3000) -> List[str]:
            sentences = text.split(". ")
            chunks = []
            current = ""
            for s in sentences:
                candidate = s + ". "
                if len(current) + len(candidate) <= max_length:
                    current += candidate
                else:
                    if current:
                        chunks.append(current.strip())
                    current = candidate
            if current:
                chunks.append(current.strip())
            return chunks

        audio_urls = []
        for i, chunk in enumerate(split_text(text)):
            murf_filename = f"murf_{filename.replace('.webm', f'_{i}.mp3')}"
            audio_url = await self.generate_speech(chunk, murf_filename, output_dir)
            audio_urls.append(audio_url)
        return audio_urls