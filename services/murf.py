import base64
import websockets
import json
import logging
import asyncio
from typing import AsyncGenerator, Optional, List
import aiofiles
import os
import httpx


class MurfService:
    """
    Murf TTS integration.

    - generate_speech(): returns raw audio bytes (mp3 by default via HTTP API)
    - generate_speech_to_file(): saves audio to /Uploads and returns a URL
    - generate_speech_chunks(): splits text into sentences, saves chunked MP3s, returns a list of URLs
    - stream_to_speech_websocket(): accepts a text async generator and yields audio bytes as they arrive from Murf WS
    """

    def __init__(self, api_key: Optional[str]):
        self.api_key = api_key
        self.logger = logging.getLogger(__name__)

    async def generate_speech(self, text: str, filename: str, output_dir: str) -> bytes:
        """
        Synchronous-style HTTP TTS → returns audio bytes.
        Caller is responsible for saving.
        """
        if not self.api_key:
            raise RuntimeError("Murf API key not set")

        url = "https://api.murf.ai/v1/speech/generate"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "text": text,
            "voiceId": "en-US-natalie",
            "sampleRate": 16000,
            "bitRate": 256,
            "encoding": "mp3",  # mp3 bytes returned
        }

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(url, json=payload, timeout=60.0)
                resp.raise_for_status()
                audio_data = resp.content
                self.logger.info("Generated speech via HTTP API: %d bytes", len(audio_data))
                return audio_data
            except httpx.HTTPStatusError as e:
                self.logger.error("HTTP API error: %s - %s", e.response.status_code, e.response.text)
                raise

    async def generate_speech_to_file(self, text: str, filename: str, output_dir: str) -> str:
        """
        HTTP TTS and save result to disk. Returns a URL under /Uploads.
        """
        audio_data = await self.generate_speech(text, filename, output_dir)
        name_no_ext, _ = os.path.splitext(filename)
        safe_name = f"{name_no_ext}.mp3"
        out_path = os.path.join(output_dir, safe_name)
        async with aiofiles.open(out_path, "wb") as f:
            await f.write(audio_data)
        self.logger.info("Saved TTS to: %s", out_path)
        return f"/Uploads/{os.path.basename(out_path)}"

    async def generate_speech_chunks(self, text: str, filename: str, output_dir: str) -> List[str]:
        """
        Chunk the text on '.' and save each sentence as an mp3 file.
        Returns URLs for each chunk under /Uploads.
        """
        sentences = [s.strip() for s in text.split(".") if s.strip()]
        audio_urls: List[str] = []

        base = os.path.splitext(filename)[0]
        for i, sentence in enumerate(sentences):
            chunk_name = f"{base}_chunk_{i}.mp3"
            audio_bytes = await self.generate_speech(sentence, chunk_name, output_dir)
            out_path = os.path.join(output_dir, chunk_name)
            async with aiofiles.open(out_path, "wb") as f:
                await f.write(audio_bytes)
            url = f"/Uploads/{os.path.basename(out_path)}"
            audio_urls.append(url)
            self.logger.info("Saved chunk %d to %s", i, out_path)

        # If the whole text had no '.', still produce a single file.
        if not audio_urls:
            single_url = await self.generate_speech_to_file(text, filename, output_dir)
            audio_urls.append(single_url)

        return audio_urls

    async def stream_to_speech_websocket(
        self,
        text_stream: AsyncGenerator[str, None],
        context_id: str
    ) -> AsyncGenerator[bytes, None]:
        """
        Take a stream of text (e.g., from a streaming LLM) and stream it to Murf over WS.
        Yield raw audio bytes as they arrive.

        NOTE: Murf WS endpoint below is configured for WAV/PCM over the socket.
        If your frontend expects MP3, either:
          - switch Murf WS to MP3 (if supported), or
          - play as WAV on the client.
        """
        if not self.api_key:
            raise RuntimeError("Murf API key not set")

        # Murf WS parameters (per their docs). We request WAV over the socket.
        ws_url = (
            "wss://api.murf.ai/v1/speech/stream-input"
            f"?api-key={self.api_key}"
            "&sample_rate=16000"
            "&channel_type=MONO"
            "&format=WAV"
            f"&contextId={context_id}"
        )
        self.logger.info("Connecting to Murf WebSocket: %s", ws_url.split("?")[0] + "?…")

        async with websockets.connect(ws_url, ping_interval=10, ping_timeout=20, max_size=None) as ws:
            # Send voice configuration
            voice_config = {
                "type": "config",
                "voiceId": "en-US-natalie",
                "voiceGender": "Female",
                "sampleRate": 16000,
                "bitRate": 256,          # affects MP3/OGG; Murf may ignore for WAV stream
                "encoding": "pcm_s16le", # WAV payload encoding over WS
            }
            await ws.send(json.dumps(voice_config))
            self.logger.info("Sent voice config to Murf WebSocket")

            async def send_text_task() -> str:
                """
                Accumulate some chunks from the LLM, then send once to Murf.
                Returns the text used (for HTTP fallback if needed).
                """
                full_text = ""
                try:
                    # Collect at least a little text quickly
                    async for t in text_stream:
                        if t.strip():
                            full_text += t + " "
                            self.logger.info("Accumulated LLM chunk: %s", t[:80])
                            if len(full_text) >= 10:
                                break

                    # Small buffer window to grab a few more chunks
                    try:
                        # asyncio.timeout exists on Python 3.11+
                        timeout_cm = getattr(asyncio, "timeout", None)
                        if timeout_cm is None:
                            # Fallback for <3.11
                            try:
                                await asyncio.wait_for(_drain_stream(text_stream, full_text), timeout=5.0)
                            except asyncio.TimeoutError:
                                pass
                        else:
                            async with asyncio.timeout(5.0):
                                async for t2 in text_stream:
                                    if t2.strip():
                                        full_text += t2 + " "
                                        self.logger.info("Extra LLM chunk: %s", t2[:80])
                    except asyncio.TimeoutError:
                        self.logger.info("Timeout waiting for more LLM chunks")

                    full_text = full_text.strip()
                    if not full_text:
                        self.logger.warning("No text received from LLM; using default fallback")
                        full_text = "What are you doing?"

                    # Send text then close input
                    await ws.send(json.dumps({"type": "text", "value": full_text}))
                    # Allow Murf to begin synthesis
                    await asyncio.sleep(0.5)
                    await ws.send(json.dumps({"type": "end"}))
                    self.logger.info("Sent text and end signal to Murf WebSocket")
                    return full_text
                except Exception as e:
                    self.logger.error("Error sending text to Murf: %s", e)
                    raise

            async def receive_audio() -> AsyncGenerator[bytes, None]:
                """
                Receive binary audio frames (WAV/PCM) and yield them.
                """
                try:
                    # Allow up to ~30 reads (tune if needed).
                    for _ in range(60):
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=180.0)
                            if isinstance(msg, bytes):
                                if msg:
                                    self.logger.info("Received Murf WS audio chunk: %d bytes", len(msg))
                                    yield msg
                                else:
                                    self.logger.warning("Empty audio chunk from Murf WS")
                            else:
                                # Text message from Murf
                                try:
                                    payload = json.loads(msg)
                                    if payload.get("type") == "error":
                                        self.logger.error("Murf WS error: %s", payload.get("message"))
                                    else:
                                        self.logger.debug("Murf WS message: %s", payload)
                                except json.JSONDecodeError:
                                    self.logger.debug("Non-JSON text from Murf WS: %s", msg)
                        except asyncio.TimeoutError:
                            self.logger.warning("Timeout waiting for Murf audio chunk; continuing")
                            continue
                except websockets.exceptions.ConnectionClosed as e:
                    self.logger.info("Murf WebSocket closed: %s", e)
                except Exception as e:
                    self.logger.error("Error receiving audio from Murf: %s", e)

            # send, then receive
            text_used = await send_text_task()
            audio_received = False
            async for audio_bytes in receive_audio():
                audio_received = True
                yield audio_bytes

            # If nothing from WS, fall back to HTTP TTS (mp3)
            if not audio_received:
                self.logger.warning("No Murf WS audio; using HTTP fallback")
                audio_bytes = await self.generate_speech(text_used, "fallback", ".")
                # Do NOT print giant base64 to stdout; only log len.
                self.logger.info("Fallback HTTP TTS bytes: %d", len(audio_bytes))
                yield audio_bytes


async def _drain_stream(text_stream: AsyncGenerator[str, None], acc: str) -> None:
    """
    Helper for Python <3.11 to simulate asyncio.timeout(). Not used directly
    when asyncio.timeout is available.
    """
    # No-op: we rely on wait_for at the callsite.
    return
