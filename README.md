# 🎙️ FastAPI Voice Echo Bot with TTS & STT

A voice-enabled web application built with **FastAPI** that allows users to record their voice, send it to the backend, transcribe it, and play back audio responses.  
The project also supports **server-side transcription** and **text-to-speech generation** with fallback error handling.

---

## 📂 Folder Structure
project/
│── static/ # Static files (CSS, JS, audio files)
│ ├── script.js
│ ├── styles.css
│ ├── fallback_error.mp3
│ └── *.mp3 (saved audio files)
│
│── templates/ # HTML templates
│ └── index.html
│
│── uploads/ # User-uploaded recordings
│
│── tts_outputs/ # TTS-generated audio files
│
│── temp/ # Temporary files
│
│── main.py # FastAPI backend code
│── .env # Environment variables
│── README.md # Project documentation
│── requirements.txt # Python dependencies

---

## 🚀 Features

- 🎤 **Record Audio** directly from the browser.
- 🔄 **Echo Bot** — Plays back your voice recording.
- 📝 **Speech-to-Text (STT)** transcription using AssemblyAI (or configured provider).
- 🔊 **Text-to-Speech (TTS)** generation for AI responses.
- ⚡ **Error Handling** — Fallback audio in case of failures.
- 🌐 **FastAPI + JavaScript UI** for real-time interaction.
- 🎨 Modern, responsive UI with separate styles for Start/Stop buttons.

---

## 🛠️ Tech Stack

- **Backend:** [FastAPI](https://fastapi.tiangolo.com/)  
- **Frontend:** HTML, CSS, JavaScript  
- **Audio Processing:** Web Audio API, AssemblyAI (STT), TTS API  
- **Other:** aiofiles, httpx, python-dotenv  

---

## 📦 Installation

1️⃣ **Clone the repository**
```bash
git clone https://github.com/kundanmehta01/voice-agent.git
cd voice-echo-bot

2️⃣ Create a virtual environment

python -m venv venv
source venv/bin/activate   # On Mac/Linux
venv\Scripts\activate      # On Windows


3️⃣ Install dependencies

pip install -r requirements.txt


4️⃣ Create .env file

ASSEMBLYAI_API_KEY=your_api_key_here
TTS_API_KEY=your_tts_api_key_here


5️⃣ Run the server

uvicorn main:app --reload


6️⃣ Open in browser
Go to: http://127.0.0.1:8000

📌 Usage

Click Start Recording to begin capturing your voice.

Click Stop Recording to upload the audio to the backend.

The backend processes it (STT → AI → TTS) and sends the audio back.

Listen to the generated response or see the transcription.

⚠️ Notes

Make sure your .env file contains valid API keys.

Clear your browser cache if updated styles are not applied.

If using AssemblyAI, ensure the audio format is supported (.wav, .mp3, .m4a).# voice-agent
# voice-echo
# voice-echo
