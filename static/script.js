// ================================
// script.js — Voice Agent Frontend
// ================================

/* ---------- State ---------- */
let mediaRecorder = null;
let audioChunks = [];
let startTime = null;
let timerInterval = null;
let isRecording = false;
let micStream = null;
let busy = false;

/* ---------- DOM ---------- */
const recordBtn = document.getElementById("recordBtn");
const echoDiv = document.getElementById("echoAudio");
const recordingStatus = document.getElementById("recordingStatus");
const timerDisplay = document.getElementById("timer");
const uploadStatus = document.getElementById("uploadStatus");
const transcriptDisplay = document.getElementById("transcriptDisplay");
const uploadedBtn = document.getElementById("uploadedAudiosBtn");
const uploadedList = document.getElementById("uploadedAudiosList");
const popupContainer = document.getElementById("popupContainer");
const clearChatBtn = document.getElementById("clearChatBtn");

/* ---------- Utils ---------- */
function getSessionId() {
    const params = new URLSearchParams(window.location.search);
    let sessionId = params.get("session_id");
    if (!sessionId) {
        sessionId = crypto.randomUUID ? crypto.randomUUID() : generateUUIDFallback();
        params.set("session_id", sessionId);
        window.history.replaceState({}, "", `${window.location.pathname}?${params}`);
    }
    return sessionId;
}

function generateUUIDFallback() {
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, c => {
        const r = crypto.getRandomValues(new Uint8Array(1))[0] & 15;
        const v = c === "x" ? r : (r & 0x3) | 0x8;
        return v.toString(16);
    });
}

function formatTime(totalSeconds) {
    const s = Math.floor(totalSeconds % 60).toString().padStart(2, "0");
    const m = Math.floor(totalSeconds / 60).toString().padStart(2, "0");
    return `${m}:${s}`;
}

function startTimer() {
    startTime = Date.now();
    stopTimer();
    timerInterval = setInterval(() => {
        const elapsed = Math.floor((Date.now() - startTime) / 1000);
        timerDisplay.textContent = formatTime(elapsed);
    }, 1000);
}

function stopTimer() {
    if (timerInterval) clearInterval(timerInterval);
    timerInterval = null;
    timerDisplay.textContent = "00:00";
}

async function safeJson(res) {
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
        try { return await res.json(); } catch { return {}; }
    }
    return {};
}

function autoScrollChat() {
    const container = transcriptDisplay.querySelector(".chat-container");
    if (container) container.scrollTop = container.scrollHeight;
}

function nowHhMm() {
    const now = new Date();
    return now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/* ---------- Chat History ---------- */
async function displayChatHistory() {
    const sessionId = getSessionId();
    try {
        const response = await fetch(`/agent/chat/${sessionId}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();

        let html = '<h3>Chat History</h3><div class="chat-container">';
        if (data.chat_history && data.chat_history.length) {
            data.chat_history.forEach(msg => {
                const sender = msg.role === "user" ? "You" : "Assistant";
                html += `
                    <div class="chat-message ${msg.role}">
                        <p><strong>${sender} (${nowHhMm()}):</strong> ${msg.content}</p>
                    </div>
                `;
            });
        } else {
            html += "<p>No chat history yet.</p>";
        }
        html += "</div>";
        transcriptDisplay.innerHTML = html;
        autoScrollChat();
    } catch (err) {
        console.error("Chat history error:", err);
        transcriptDisplay.innerHTML = `<p>❌ Error: Failed to load chat history</p>`;
    }
}

/* ---------- Recording ---------- */
async function startRecording() {
    echoDiv.innerHTML = "";
    uploadStatus.textContent = "";

    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(micStream);
    audioChunks = [];

    mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) audioChunks.push(e.data);
    };

    mediaRecorder.onstop = async () => {
        try { micStream.getTracks().forEach(t => t.stop()); } catch {}
        await uploadRecording();
    };

    mediaRecorder.start();
    isRecording = true;
    recordingStatus.style.display = "block";
    recordBtn.textContent = "⏹ Stop";
    recordBtn.classList.add("recording");
    startTimer();
}

function stopRecording() {
    if (!mediaRecorder || mediaRecorder.state !== "recording") return;
    try { mediaRecorder.stop(); } catch (e) { console.error("Stop error:", e); }
    isRecording = false;
    recordingStatus.style.display = "none";
    recordBtn.textContent = "🎤 Start Recording";
    recordBtn.classList.remove("recording");
    stopTimer();
}

/* ---------- Upload & Playback ---------- */
async function uploadRecording() {
    const audioBlob = new Blob(audioChunks, { type: "audio/webm" });
    if (audioBlob.size < 100) {
        uploadStatus.textContent = "❌ Recording too short or empty.";
        return;
    }

    const formData = new FormData();
    const filename = `audio_${Date.now()}.webm`;
    formData.append("file", audioBlob, filename);

    uploadStatus.textContent = "⏳ Processing audio...";
    const sessionId = getSessionId();

    try {
        const response = await fetch(`/agent/chat/${sessionId}`, {
            method: "POST",
            body: formData,
        });

        const data = await safeJson(response);
        if (!response.ok) {
            const errMsg = data.error || `Server error: ${response.status}`;
            uploadStatus.textContent = `❌ ${errMsg}`;
            transcriptDisplay.insertAdjacentHTML("beforeend", `<p>❌ ${errMsg}</p>`);
            console.error("Server error:", data);
            if (data.fallback_audio) playFallbackAudio(data.fallback_audio, "Fallback response");
            return;
        }

        if (data.error) {
            uploadStatus.textContent = `❌ Processing failed: ${data.error}`;
            transcriptDisplay.insertAdjacentHTML("beforeend", `<p>❌ ${data.error}</p>`);
            console.error("Processing error:", data);
            if (data.fallback_audio) playFallbackAudio(data.fallback_audio, "Fallback response");
            return;
        }

        if (data.audio_url) {
            echoDiv.innerHTML = `
                <audio controls autoplay>
                    <source src="${data.audio_url}" type="audio/mp3">
                    Your browser does not support the audio element.
                </audio>
            `;
            uploadStatus.textContent = `✅ Uploaded and processed: ${filename}`;
            await displayChatHistory();
        } else {
            uploadStatus.textContent = "❌ Processing failed: No audio URL returned.";
            console.error("No audio_url in response:", data);
            if (data.fallback_audio) playFallbackAudio(data.fallback_audio, "Fallback response");
        }

        if (uploadedList.style.display === "block") {
            await loadUploadedAudios();
        }
    } catch (err) {
        uploadStatus.textContent = "❌ Upload failed.";
        console.error("Upload error:", err);
        transcriptDisplay.insertAdjacentHTML("beforeend", `<p>❌ Network or server issue - ${err.message}</p>`);
    }
}

function playFallbackAudio(url, label = "Fallback") {
    echoDiv.innerHTML = `
        <p>🔊 ${label}:</p>
        <audio controls autoplay>
            <source src="${url}" type="audio/mp3">
            Your browser does not support the audio element.
        </audio>
    `;
    uploadStatus.textContent = "⚠️ Playing fallback audio";
}

/* ---------- Toggle Button ---------- */
async function onRecordBtnClick() {
    if (busy) return;
    busy = true;
    try {
        if (!isRecording) {
            await startRecording();
        } else {
            stopRecording();
        }
    } catch (err) {
        console.error("Toggle error:", err);
        alert("Microphone access denied or unavailable.");
    } finally {
        busy = false;
    }
}

/* ---------- Uploaded Audios ---------- */
uploadedBtn.addEventListener("click", () => {
    const visible = uploadedList.style.display === "block";
    if (visible) {
        uploadedList.style.display = "none";
        popupContainer.innerHTML = "";
    } else {
        uploadedList.style.display = "block";
        loadUploadedAudios();
    }
});

async function loadUploadedAudios() {
    try {
        const res = await fetch("/list-audios");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const audios = await res.json();

        if (!Array.isArray(audios) || !audios.length) {
            uploadedList.innerHTML = "<p>No audio files uploaded yet.</p>";
            return;
        }

        uploadedList.innerHTML = `
            <table class="audio-table">
                <thead><tr><th>#</th><th>Audio Name</th></tr></thead>
                <tbody>
                    ${audios
                        .map((name, i) => `
                            <tr onclick="showPopup('${name.replace(/'/g, "\\'")}')">
                                <td>${i + 1}</td>
                                <td>${name}</td>
                            </tr>
                        `)
                        .join("")}
                </tbody>
            </table>
        `;
    } catch (err) {
        console.error("Load audios error:", err);
        uploadedList.innerHTML = "<p>Error loading uploaded files.</p>";
    }
}

window.showPopup = function (filename) {
    const audioType = filename.endsWith(".mp3") ? "audio/mp3" : "audio/webm";
    popupContainer.innerHTML = `
        <div class="popup">
            <div class="popup-content">
                <span class="close-btn" onclick="closePopup()">×</span>
                <p><strong>${filename}</strong></p>
                <audio controls autoplay>
                    <source src="/Uploads/${filename}" type="${audioType}">
                    Your browser does not support the audio element.
                </audio>
            </div>
        </div>
    `;
};

window.closePopup = function () {
    popupContainer.innerHTML = "";
};

/* ---------- Clear Chat ---------- */
clearChatBtn.addEventListener("click", async () => {
    const sessionId = getSessionId();
    if (!sessionId) {
        alert("No session ID found!");
        return;
    }
    if (!confirm("Are you sure you want to clear this chat history?")) return;

    try {
        const res = await fetch(`/agent/chat/${sessionId}`, { method: "DELETE" });
        const data = await safeJson(res);
        if (res.ok) {
            alert("✅ Chat history cleared.");
            echoDiv.innerHTML = "";
            await displayChatHistory();
        } else {
            alert(`❌ Error: ${data.error || "Failed to clear chat"}`);
            if (data.fallback_audio) playFallbackAudio(data.fallback_audio, "Fallback response");
        }
    } catch (err) {
        console.error("Error clearing chat:", err);
        alert("❌ Failed to clear chat history.");
    }
});

/* ---------- Init ---------- */
document.addEventListener("DOMContentLoaded", () => {
    recordBtn.addEventListener("click", onRecordBtnClick);
    displayChatHistory();
});