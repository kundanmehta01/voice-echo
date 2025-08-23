import asyncio
import base64
import json
import logging
import os
import uuid
import re
from fastapi import FastAPI, UploadFile, File, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel
from assemblyai.streaming.v3 import (
    StreamingClient,
    StreamingClientOptions,
    StreamingParameters,
    StreamingEvents,
)
from services.assemblyai import AssemblyAIService
from services.gemini import GeminiService
from services.murf import MurfService
import aiofiles
import httpx

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# FastAPI Setup
app = FastAPI(title="Voice Agent API")
load_dotenv()

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Permissions-Policy"],
)

# Permissions Policy Middleware
@app.middleware("http")
async def add_permissions_policy_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["Permissions-Policy"] = "unload=()"
    return response

# Directory Configuration
UPLOAD_DIR = "Uploads"
TEMP_DIR = "temp"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/Uploads", StaticFiles(directory=UPLOAD_DIR), name="Uploads")
templates = Jinja2Templates(directory="templates")

# Service Initialization
assemblyai_service = AssemblyAIService(os.getenv("ASSEMBLYAI_API_KEY"))
gemini_service = GeminiService(os.getenv("GEMINI_API_KEY"))
murf_service = MurfService(os.getenv("MURF_API_KEY"))

# In-memory Chat History
chat_history = {}

# Pydantic Models
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatResponse(BaseModel):
    audio_url: str
    transcript: str
    llm_response: str
    chat_history: list[ChatMessage]
    additional_audio_urls: list[str]
    session_id: str

class TranscriptionResponse(BaseModel):
    transcript: str

class AudioUploadResponse(BaseModel):
    name: str
    content_type: str
    size: int

class ErrorResponse(BaseModel):
    error: str
    fallback_audio: str | None = "/static/fallback_error.mp3"

# Helper Functions
def error_response(message: str, status_code: int = 500) -> JSONResponse:
    logger.error("Error: %s", message)
    return JSONResponse(
        content={"error": message, "fallback_audio": "/static/fallback_error.mp3"},
        status_code=status_code,
    )

def clean_transcript(transcript: str) -> str:
    """Remove repetitive phrases and normalize transcript."""
    transcript = re.sub(r'[^\w\s]', '', transcript.lower()).strip()
    words = transcript.split()
    seen = set()
    unique_words = []
    for word in words:
        if word not in seen or len(unique_words) < 10:
            unique_words.append(word)
            seen.add(word)
    return " ".join(unique_words).capitalize()

# Routes
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    try:
        return templates.TemplateResponse("index.html", {"request": request})
    except Exception as e:
        logger.error("Error serving index.html: %s", e)
        raise HTTPException(status_code=404, detail="index.html not found")

@app.get("/favicon.ico")
async def favicon():
    """Handle favicon.ico requests."""
    return Response(status_code=204)

@app.get("/agent/chat/{session_id}")
async def get_chat_history(session_id: str):
    logger.info("Fetching chat history for session: %s", session_id)
    return {"chat_history": chat_history.get(session_id, [])}

@app.post("/upload-audio", response_model=AudioUploadResponse)
async def upload_audio(file: UploadFile = File(...)):
    try:
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        async with aiofiles.open(file_path, "wb") as out_file:
            content = await file.read()
            await out_file.write(content)
        logger.info("Uploaded audio: %s, size=%d bytes", file.filename, len(content))
        return AudioUploadResponse(
            name=file.filename,
            content_type=file.content_type,
            size=os.path.getsize(file_path),
        )
    except Exception as e:
        logger.exception("Upload audio error: %s", e)
        raise HTTPException(status_code=500, detail={"error": str(e), "fallback_audio": "/static/fallback_error.mp3"})

@app.get("/list-audios")
async def list_audios():
    try:
        files = sorted(os.listdir(UPLOAD_DIR))
        logger.info("Listed %d uploaded audios", len(files))
        return files
    except Exception as e:
        logger.exception("List audios error: %s", e)
        raise HTTPException(status_code=500, detail={"error": str(e), "fallback_audio": "/static/fallback_error.mp3"})

@app.post("/transcribe/file", response_model=TranscriptionResponse)
async def transcribe_audio(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) < 100:
        logger.error("Audio file too small: %s bytes", len(content))
        raise HTTPException(status_code=400, detail={"error": "Audio file is too small or empty", "fallback_audio": "/static/fallback_error.mp3"})

    temp_path = os.path.join(TEMP_DIR, file.filename)
    async with aiofiles.open(temp_path, "wb") as out_file:
        await out_file.write(content)

    try:
        transcript = await assemblyai_service.transcribe_audio(temp_path)
        if not transcript.strip():
            await assemblyai_service.cleanup(temp_path)
            logger.warning("Transcription empty for file: %s", file.filename)
            raise HTTPException(status_code=400, detail={"error": "Transcription is empty or silent audio", "fallback_audio": "/static/fallback_error.mp3"})
        await assemblyai_service.cleanup(temp_path)
        logger.info("Transcribed file %s: %s", file.filename, transcript[:80])
        return TranscriptionResponse(transcript=transcript)
    except Exception as e:
        logger.exception("Transcription error for %s: %s", file.filename, e)
        await assemblyai_service.cleanup(temp_path)
        raise HTTPException(status_code=500, detail={"error": str(e), "fallback_audio": "/static/fallback_error.mp3"})

@app.post("/tts/echo")
async def tts_echo(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) < 100:
        logger.error("Audio file too small: %s bytes", len(content))
        raise HTTPException(status_code=400, detail={"error": "Audio file is too small or empty", "fallback_audio": "/static/fallback_error.mp3"})

    temp_path = os.path.join(TEMP_DIR, file.filename)
    async with aiofiles.open(temp_path, "wb") as out_file:
        await out_file.write(content)

    try:
        transcript = await assemblyai_service.transcribe_audio(temp_path)
        if not transcript.strip():
            await assemblyai_service.cleanup(temp_path)
            logger.warning("Transcription empty for file: %s", file.filename)
            raise HTTPException(status_code=400, detail={"error": "Invalid or empty transcription text", "fallback_audio": "/static/fallback_error.mp3"})

        audio_url = await murf_service.generate_speech_to_file(
            text=transcript,
            filename=file.filename,
            output_dir=UPLOAD_DIR,
        )
        await assemblyai_service.cleanup(temp_path)
        logger.info("TTS echo for %s: transcript=%s, audio_url=%s", file.filename, transcript[:80], audio_url)
        return {"audio_url": audio_url, "transcript": transcript}
    except Exception as e:
        logger.exception("TTS echo error for %s: %s", file.filename, e)
        await assemblyai_service.cleanup(temp_path)
        raise HTTPException(status_code=500, detail={"error": str(e), "fallback_audio": "/static/fallback_error.mp3"})

@app.post("/llm/query")
async def llm_query(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) < 100:
        logger.error("Audio file too small: %s bytes", len(content))
        raise HTTPException(status_code=400, detail={"error": "Audio file is too small or empty", "fallback_audio": "/static/fallback_error.mp3"})

    temp_path = os.path.join(TEMP_DIR, file.filename)
    async with aiofiles.open(temp_path, "wb") as out_file:
        await out_file.write(content)

    try:
        transcript = await assemblyai_service.transcribe_audio(temp_path)
        if not transcript.strip():
            await assemblyai_service.cleanup(temp_path)
            logger.warning("Transcription empty for file: %s", file.filename)
            raise HTTPException(status_code=400, detail={"error": "Transcription is empty or silent audio", "fallback_audio": "/static/fallback_error.mp3"})

        accumulated_response = ""
        async for chunk in gemini_service.generate_streaming_content(transcript):
            accumulated_response += chunk
            logger.info("LLM chunk: %s", chunk[:80])

        if not accumulated_response:
            await assemblyai_service.cleanup(temp_path)
            logger.error("No response from Gemini API for transcript: %s", transcript[:80])
            raise HTTPException(status_code=500, detail={"error": "No response from Gemini API", "fallback_audio": "/static/fallback_error.mp3"})

        audio_urls = await murf_service.generate_speech_chunks(
            text=accumulated_response,
            filename=file.filename,
            output_dir=UPLOAD_DIR,
        )
        await assemblyai_service.cleanup(temp_path)
        logger.info("LLM query for %s: transcript=%s, response=%s, audio_urls=%s", file.filename, transcript[:80], accumulated_response[:80], audio_urls)
        return {
            "audio_url": audio_urls[0],
            "transcript": transcript,
            "llm_response": accumulated_response,
            "additional_audio_urls": audio_urls[1:] if len(audio_urls) > 1 else [],
        }
    except Exception as e:
        logger.exception("LLM query error for %s: %s", file.filename, e)
        await assemblyai_service.cleanup(temp_path)
        raise HTTPException(status_code=500, detail={"error": str(e), "fallback_audio": "/static/fallback_error.mp3"})

@app.post("/agent/chat/{session_id}", response_model=ChatResponse)
async def agent_chat(session_id: str, file: UploadFile = File(...)):
    content = await file.read()
    if len(content) < 100:
        logger.error("Audio file too small: %s bytes", len(content))
        raise HTTPException(status_code=400, detail={"error": "Audio file is too small or empty", "fallback_audio": "/static/fallback_error.mp3"})

    temp_path = os.path.join(TEMP_DIR, file.filename)
    async with aiofiles.open(temp_path, "wb") as out_file:
        await out_file.write(content)

    try:
        transcript = await assemblyai_service.transcribe_audio(temp_path)
        if not transcript.strip():
            await assemblyai_service.cleanup(temp_path)
            logger.warning("Transcription empty for file: %s", file.filename)
            raise HTTPException(status_code=400, detail={"error": "Transcription is empty or silent audio", "fallback_audio": "/static/fallback_error.mp3"})

        if session_id not in chat_history:
            chat_history[session_id] = []
        chat_history[session_id].append(ChatMessage(role="user", content=transcript))

        llm_response = await gemini_service.generate_content_with_history(chat_history[session_id])
        if not llm_response:
            await assemblyai_service.cleanup(temp_path)
            logger.error("No response from Gemini API for transcript: %s", transcript[:80])
            raise HTTPException(status_code=500, detail={"error": "No response from Gemini API", "fallback_audio": "/static/fallback_error.mp3"})

        chat_history[session_id].append(ChatMessage(role="assistant", content=llm_response))

        audio_urls = await murf_service.generate_speech_chunks(
            text=llm_response,
            filename=file.filename,
            output_dir=UPLOAD_DIR,
        )
        await assemblyai_service.cleanup(temp_path)
        logger.info("Agent chat for session %s: transcript=%s, response=%s, audio_urls=%s", session_id, transcript[:80], llm_response[:80], audio_urls)
        return ChatResponse(
            audio_url=audio_urls[0],
            transcript=transcript,
            llm_response=llm_response,
            chat_history=chat_history[session_id],
            additional_audio_urls=audio_urls[1:],
            session_id=session_id,
        )
    except Exception as e:
        logger.exception("Agent chat error for session %s: %s", session_id, e)
        await assemblyai_service.cleanup(temp_path)
        raise HTTPException(status_code=500, detail={"error": str(e), "fallback_audio": "/static/fallback_error.mp3"})

@app.delete("/agent/chat/{session_id}")
async def delete_chat_history(session_id: str):
    try:
        if session_id in chat_history:
            del chat_history[session_id]
            logger.info("Chat history deleted for session: %s", session_id)
            return {"message": f"Chat history for session {session_id} deleted"}
        raise HTTPException(status_code=404, detail={"error": "Session not found", "fallback_audio": "/static/fallback_error.mp3"})
    except Exception as e:
        logger.exception("Delete chat history error for session %s: %s", session_id, e)
        raise HTTPException(status_code=500, detail={"error": str(e), "fallback_audio": "/static/fallback_error.mp3"})

@app.get("/health")
async def health():
    return {"status": "ok"}

# Helper function to convert WAV to MP3 for client compatibility
async def convert_wav_to_mp3(wav_bytes: bytes) -> str:
    """Convert WAV audio to MP3 using ffmpeg-python (requires ffmpeg installed)."""
    try:
        import ffmpeg
        import io
        input_stream = io.BytesIO(wav_bytes)
        output_stream = io.BytesIO()
        stream = ffmpeg.input('pipe:', format='wav').output('pipe:', format='mp3', acodec='mp3', ar=16000, ac=1).run_async(pipe_stdin=True, pipe_stdout=True)
        stdout, _ = stream.communicate(input=wav_bytes)
        output_stream.write(stdout)
        mp3_base64 = base64.b64encode(output_stream.getvalue()).decode('utf-8')
        logger.info("Converted WAV to MP3: %d bytes", len(mp3_base64))
        return mp3_base64
    except Exception as e:
        logger.error("Failed to convert WAV to MP3: %s", e)
        return base64.b64encode(wav_bytes).decode('utf-8')  # Fallback to WAV base64

# WebSocket endpoint (AssemblyAI stream in, Murf stream out)
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("\n✅ WebSocket audio connection established\n")
    loop = asyncio.get_event_loop()
    ws_open = True
    session_id = str(uuid.uuid4())
    last_transcript = ""
    processing_lock = asyncio.Lock()
    audio_buffer = bytearray()
    min_bytes = 1600  # 50 ms at 16 kHz (800 samples * 2 bytes)

    logger.info("✅ Client connected: %s", session_id)

    def on_begin(client, event):
        logger.info("AAI session started: %s", event.id)
        print("\n🎤 Ready to receive audio from browser (16kHz, 16-bit PCM)\n")

    def on_turn(client, event):
        logger.info(
            "AAI Turn: end_of_turn=%s, text=%s",
            getattr(event, "end_of_turn", False),
            getattr(event, "transcript", "")[:80] or "<empty>",
        )
        asyncio.run_coroutine_threadsafe(handle_turn(event), loop)

    async def handle_turn(event):
        nonlocal last_transcript, ws_open
        if not ws_open:
            logger.debug("Handle turn ignored, session inactive")
            return

        transcript = (event.transcript or "").strip()
        if not transcript:
            logger.warning("Empty transcript received from AssemblyAI")
            if ws_open:
                await websocket.send_json({"type": "transcript", "text": "", "is_final": False, "end_of_turn": False})
                await websocket.send_json({"type": "error", "message": "No speech detected"})
            return

        logger.info("Processing transcript: %s", transcript[:80])
        try:
            await websocket.send_json({
                "type": "transcript",
                "text": transcript,
                "is_final": getattr(event, "end_of_turn", False),
                "end_of_turn": getattr(event, "end_of_turn", False)
            })
        except Exception as e:
            logger.debug("WS send transcript failed (non-fatal): %s", e)

        async with processing_lock:
            if getattr(event, "end_of_turn", False):
                normalized_text = clean_transcript(transcript)
                if not normalized_text:
                    logger.warning("Cleaned transcript is empty, skipping processing")
                    await websocket.send_json({"type": "error", "message": "Cleaned transcript is empty"})
                    return
                if normalized_text.lower() == last_transcript.lower():
                    logger.info("Duplicate final transcript, skipping")
                    return
                last_transcript = normalized_text
                print(f"\n👤 USER: {normalized_text}")

                await websocket.send_json({"type": "llm_start", "message": "Generating response..."})

                try:
                    logger.info("Sending transcript to Gemini: %s", normalized_text[:80])
                    accumulated_response = ""
                    text_chunks = []
                    async for chunk in gemini_service.generate_streaming_content(normalized_text):
                        accumulated_response += chunk
                        text_chunks.append(chunk)
                        logger.info("LLM chunk: %s", chunk[:80])
                        await websocket.send_json({"type": "llm_chunk", "text": chunk})

                    print(f"\n🤖 ASSISTANT: {accumulated_response}")
                    await websocket.send_json({"type": "llm_complete", "full_response": accumulated_response})

                    # Use HTTP-based TTS (MP3) instead of WebSocket for compatibility
                    print("\n📢 Using HTTP-based TTS...")
                    chunk_index = 0
                    for text_chunk in text_chunks:
                        chunk_index += 1
                        try:
                            audio_bytes = await murf_service.generate_speech(
                                text=text_chunk,
                                filename=f"chunk_{chunk_index}.mp3",
                                output_dir=UPLOAD_DIR
                            )
                            if audio_bytes and len(audio_bytes) >= 100:
                                audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
                                print(f"\n🔊 Base64 Audio Chunk {chunk_index} (length: {len(audio_base64)} bytes):")
                                print(f"{audio_base64[:200]}..." if len(audio_base64) > 200 else audio_base64)
                                await websocket.send_json({
                                    "type": "tts_audio",
                                    "audio_base64": audio_base64,
                                    "chunk_index": chunk_index
                                })
                                logger.info("✅ Sent audio chunk (%d bytes, format=mp3)", len(audio_bytes))
                        except Exception as e:
                            logger.error("Failed to generate/send audio chunk %d: %s", chunk_index, e)
                except Exception as e:
                    logger.error("LLM/Murf processing error: %s", e)
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Failed to process LLM or Murf response: {str(e)}"
                    })

    def on_error(client, error):
        logger.error("AAI Streaming error: %s", error)
        asyncio.run_coroutine_threadsafe(handle_error(error), loop)

    async def handle_error(error):
        nonlocal ws_open
        if not ws_open:
            return
        logger.error("Sending error to client: %s", error)
        try:
            await websocket.send_json({"type": "error", "message": str(error)})
        except Exception:
            pass

    def on_terminated(client, event):
        logger.info("AAI session terminated after %ss", getattr(event, "audio_duration_seconds", "?"))
        asyncio.run_coroutine_threadsafe(handle_terminated(event), loop)

    async def handle_terminated(event):
        nonlocal ws_open
        logger.info("AAI session terminated")
        ws_open = False

    try:
        client = StreamingClient(
            StreamingClientOptions(
                api_key=os.getenv("ASSEMBLYAI_API_KEY"),
                api_host="streaming.assemblyai.com",
            )
        )
        logger.info("Initialized AssemblyAI client")
    except Exception as e:
        logger.error("Failed to initialize AssemblyAI client: %s", e)
        await websocket.send_json({"type": "error", "message": "Failed to initialize AssemblyAI client"})
        await websocket.close()
        return

    client.on(StreamingEvents.Begin, on_begin)
    client.on(StreamingEvents.Turn, on_turn)
    client.on(StreamingEvents.Error, on_error)
    client.on(StreamingEvents.Termination, on_terminated)

    try:
        client.connect(
            StreamingParameters(
                sample_rate=16000,
                format_turns=True,
                disable_partial_transcripts=False,  # Enable partial transcripts
                word_boost=["hello", "how", "are", "you", "what", "doing"],
                speech_threshold=0.01,  # Keep high sensitivity
            )
        )
        logger.info("Connected to AssemblyAI")
        print("\n🎤 Ready to receive audio from browser (16kHz, 16-bit PCM)\n")
    except Exception as e:
        logger.error("Failed to connect to AssemblyAI: %s", e)
        await websocket.send_json({"type": "error", "message": "Failed to connect to AssemblyAI"})
        await websocket.close()
        return

    try:
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive(), timeout=120.0)
                if "bytes" in msg and msg["bytes"]:
                    logger.info("📡 Received %d bytes from client mic", len(msg["bytes"]))
                    audio_buffer.extend(msg["bytes"])
                    while len(audio_buffer) >= min_bytes:
                        chunk = audio_buffer[:min_bytes]
                        audio_buffer = audio_buffer[min_bytes:]
                        if isinstance(chunk, (bytes, bytearray)):
                            client.stream(chunk)
                            logger.info("📤 Streamed %d bytes to AssemblyAI", len(chunk))
                        else:
                            logger.error("Invalid chunk type: %s", type(chunk))
                elif "text" in msg and msg["text"]:
                    data = json.loads(msg["text"])
                    if data.get("type") == "end" or msg["text"].strip().upper() == "EOF":
                        logger.info("Received EOF/end signal, processing remaining buffer")
                        async with processing_lock:
                            while len(audio_buffer) >= min_bytes:
                                chunk = audio_buffer[:min_bytes]
                                audio_buffer = audio_buffer[min_bytes:]
                                if isinstance(chunk, (bytes, bytearray)):
                                    client.stream(chunk)
                                    logger.info("📤 Streamed remaining %d bytes to AssemblyAI", len(chunk))
                            if audio_buffer:
                                chunk = bytes(audio_buffer)
                                if isinstance(chunk, (bytes, bytearray)) and len(chunk) >= 100:
                                    client.stream(chunk)
                                    logger.info("📤 Streamed final %d bytes to AssemblyAI", len(chunk))
                                audio_buffer.clear()
                            await asyncio.sleep(1.0)  # Allow AssemblyAI to process
                        break
            except asyncio.TimeoutError:
                logger.info("Timeout reached, processing remaining buffer")
                async with processing_lock:
                    while len(audio_buffer) >= min_bytes:
                        chunk = audio_buffer[:min_bytes]
                        audio_buffer = audio_buffer[min_bytes:]
                        if isinstance(chunk, (bytes, bytearray)):
                            client.stream(chunk)
                            logger.info("📤 Streamed remaining %d bytes to AssemblyAI", len(chunk))
                    if audio_buffer:
                        chunk = bytes(audio_buffer)
                        if isinstance(chunk, (bytes, bytearray)) and len(chunk) >= 100:
                            client.stream(chunk)
                            logger.info("📤 Streamed final %d bytes to AssemblyAI", len(chunk))
                        audio_buffer.clear()
                    await asyncio.sleep(1.0)  # Allow AssemblyAI to process
                break
            except WebSocketDisconnect:
                logger.info("WebSocket disconnected by client")
                break
            except Exception as e:
                logger.error("WebSocket error: %s", e)
                break
    finally:
        ws_open = False
        try:
            client.disconnect(terminate=True)
            logger.info("AssemblyAI client disconnected")
            print("\n❌ WebSocket audio connection closed\n")
        except Exception as e:
            logger.warning("Error during AAI disconnect: %s", e)
        try:
            await websocket.close()
            logger.info("WebSocket closed cleanly ✅")
        except Exception:
            logger.warning("Error closing WebSocket")