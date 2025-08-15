import os
import logging
import aiofiles
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel
from services.assemblyai import AssemblyAIService
from services.murf import MurfService
from services.gemini import GeminiService

# -------------------------
# Logging Configuration
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# -------------------------
# FastAPI Setup
# -------------------------
app = FastAPI(title="Voice Agent API")
load_dotenv()

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Permissions Policy Middleware
@app.middleware("http")
async def add_permissions_policy_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["Permissions-Policy"] = "unload=()"
    return response

# -------------------------
# Directory Configuration
# -------------------------
UPLOAD_DIR = "Uploads"
TEMP_DIR = "temp"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/Uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
templates = Jinja2Templates(directory="templates")

# -------------------------
# Service Initialization
# -------------------------
assemblyai_service = AssemblyAIService(os.getenv("ASSEMBLYAI_API_KEY"))
murf_service = MurfService(os.getenv("MURF_API_KEY"))
gemini_service = GeminiService(os.getenv("GEMINI_API_KEY"))

# -------------------------
# In-memory Chat History
# -------------------------
chat_history = {}

# -------------------------
# Pydantic Models
# -------------------------
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatResponse(BaseModel):
    audio_url: str
    transcript: str
    llm_response: str
    chat_history: List[ChatMessage]
    additional_audio_urls: List[str]
    session_id: str

class TranscriptionResponse(BaseModel):
    transcript: str

class AudioUploadResponse(BaseModel):
    name: str
    content_type: str
    size: int

class ErrorResponse(BaseModel):
    error: str
    fallback_audio: Optional[str] = "/static/fallback_error.mp3"

# -------------------------
# Helper Functions
# -------------------------
def error_response(message: str, status_code: int = 500) -> JSONResponse:
    logger.error("Error: %s", message)
    return JSONResponse(
        content={"error": message, "fallback_audio": "/static/fallback_error.mp3"},
        status_code=status_code
    )

# -------------------------
# Routes
# -------------------------
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/agent/chat/{session_id}")
async def get_chat_history(session_id: str):
    return {"chat_history": chat_history.get(session_id, [])}

@app.post("/upload-audio", response_model=AudioUploadResponse)
async def upload_audio(file: UploadFile = File(...)):
    try:
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        async with aiofiles.open(file_path, "wb") as out_file:
            content = await file.read()
            await out_file.write(content)
        return AudioUploadResponse(
            name=file.filename,
            content_type=file.content_type,
            size=os.path.getsize(file_path)
        )
    except Exception as e:
        logger.exception("Upload audio error")
        raise HTTPException(status_code=500, detail={"error": str(e), "fallback_audio": "/static/fallback_error.mp3"})

@app.get("/list-audios")
async def list_audios():
    try:
        files = sorted(os.listdir(UPLOAD_DIR))
        return files
    except Exception as e:
        logger.exception("List audios error")
        raise HTTPException(status_code=500, detail={"error": str(e), "fallback_audio": "/static/fallback_error.mp3"})

@app.post("/transcribe/file", response_model=TranscriptionResponse)
async def transcribe_audio(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) < 100:
        raise HTTPException(status_code=400, detail={"error": "Audio file is too small or empty", "fallback_audio": "/static/fallback_error.mp3"})

    temp_path = os.path.join(TEMP_DIR, file.filename)
    async with aiofiles.open(temp_path, "wb") as out_file:
        await out_file.write(content)

    try:
        transcript = await assemblyai_service.transcribe_audio(temp_path)
        if not transcript.strip():
            await assemblyai_service.cleanup(temp_path)
            raise HTTPException(status_code=400, detail={"error": "Transcription is empty or silent audio", "fallback_audio": "/static/fallback_error.mp3"})
        await assemblyai_service.cleanup(temp_path)
        return TranscriptionResponse(transcript=transcript)
    except Exception as e:
        logger.exception("Transcription error")
        await assemblyai_service.cleanup(temp_path)
        raise HTTPException(status_code=500, detail={"error": str(e), "fallback_audio": "/static/fallback_error.mp3"})

@app.post("/tts/echo")
async def tts_echo(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) < 100:
        raise HTTPException(status_code=400, detail={"error": "Audio file is too small or empty", "fallback_audio": "/static/fallback_error.mp3"})

    temp_path = os.path.join(TEMP_DIR, file.filename)
    async with aiofiles.open(temp_path, "wb") as out_file:
        await out_file.write(content)

    try:
        transcript = await assemblyai_service.transcribe_audio(temp_path)
        if not transcript.strip():
            await assemblyai_service.cleanup(temp_path)
            raise HTTPException(status_code=400, detail={"error": "Invalid or empty transcription text", "fallback_audio": "/static/fallback_error.mp3"})

        audio_url = await murf_service.generate_speech(
            text=transcript,
            filename=file.filename,
            output_dir=UPLOAD_DIR
        )
        await assemblyai_service.cleanup(temp_path)
        return {"audio_url": audio_url, "transcript": transcript}
    except Exception as e:
        logger.exception("TTS echo error")
        await assemblyai_service.cleanup(temp_path)
        raise HTTPException(status_code=500, detail={"error": str(e), "fallback_audio": "/static/fallback_error.mp3"})

@app.post("/llm/query")
async def llm_query(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) < 100:
        raise HTTPException(status_code=400, detail={"error": "Audio file is too small or empty", "fallback_audio": "/static/fallback_error.mp3"})

    temp_path = os.path.join(TEMP_DIR, file.filename)
    async with aiofiles.open(temp_path, "wb") as out_file:
        await out_file.write(content)

    try:
        transcript = await assemblyai_service.transcribe_audio(temp_path)
        if not transcript.strip():
            await assemblyai_service.cleanup(temp_path)
            raise HTTPException(status_code=400, detail={"error": "Transcription is empty or silent audio", "fallback_audio": "/static/fallback_error.mp3"})

        llm_response = await gemini_service.generate_content(transcript)
        if not llm_response:
            await assemblyai_service.cleanup(temp_path)
            raise HTTPException(status_code=500, detail={"error": "No response from Gemini API", "fallback_audio": "/static/fallback_error.mp3"})

        audio_urls = await murf_service.generate_speech_chunks(
            text=llm_response,
            filename=file.filename,
            output_dir=UPLOAD_DIR
        )
        await assemblyai_service.cleanup(temp_path)
        return {
            "audio_url": audio_urls[0],
            "transcript": transcript,
            "llm_response": llm_response,
            "additional_audio_urls": audio_urls[1:] if len(audio_urls) > 1 else []
        }
    except Exception as e:
        logger.exception("LLM query error")
        await assemblyai_service.cleanup(temp_path)
        raise HTTPException(status_code=500, detail={"error": str(e), "fallback_audio": "/static/fallback_error.mp3"})

@app.post("/agent/chat/{session_id}", response_model=ChatResponse)
async def agent_chat(session_id: str, file: UploadFile = File(...)):
    content = await file.read()
    if len(content) < 100:
        raise HTTPException(status_code=400, detail={"error": "Audio file is too small or empty", "fallback_audio": "/static/fallback_error.mp3"})

    temp_path = os.path.join(TEMP_DIR, file.filename)
    async with aiofiles.open(temp_path, "wb") as out_file:
        await out_file.write(content)

    try:
        transcript = await assemblyai_service.transcribe_audio(temp_path)
        if not transcript.strip():
            await assemblyai_service.cleanup(temp_path)
            raise HTTPException(status_code=400, detail={"error": "Transcription is empty or silent audio", "fallback_audio": "/static/fallback_error.mp3"})

        # Update chat history
        if session_id not in chat_history:
            chat_history[session_id] = []
        chat_history[session_id].append(ChatMessage(role="user", content=transcript))

        # Get LLM response
        llm_response = await gemini_service.generate_content_with_history(chat_history[session_id])
        if not llm_response:
            await assemblyai_service.cleanup(temp_path)
            raise HTTPException(status_code=500, detail={"error": "No response from Gemini API", "fallback_audio": "/static/fallback_error.mp3"})

        chat_history[session_id].append(ChatMessage(role="assistant", content=llm_response))

        # Generate audio
        audio_urls = await murf_service.generate_speech_chunks(
            text=llm_response,
            filename=file.filename,
            output_dir=UPLOAD_DIR
        )
        await assemblyai_service.cleanup(temp_path)

        return ChatResponse(
            audio_url=audio_urls[0],
            transcript=transcript,
            llm_response=llm_response,
            chat_history=chat_history[session_id],
            additional_audio_urls=audio_urls[1:],
            session_id=session_id
        )
    except Exception as e:
        logger.exception("Agent chat error")
        await assemblyai_service.cleanup(temp_path)
        raise HTTPException(status_code=500, detail={"error": str(e), "fallback_audio": "/static/fallback_error.mp3"})

@app.delete("/agent/chat/{session_id}")
async def delete_chat_history(session_id: str):
    try:
        if session_id in chat_history:
            del chat_history[session_id]
            return {"message": f"Chat history for session {session_id} deleted"}
        raise HTTPException(status_code=404, detail={"error": "Session not found", "fallback_audio": "/static/fallback_error.mp3"})
    except Exception as e:
        logger.exception("Delete chat history error")
        raise HTTPException(status_code=500, detail={"error": str(e), "fallback_audio": "/static/fallback_error.mp3"})

@app.get("/health")
async def health():
    return {"status": "ok"}