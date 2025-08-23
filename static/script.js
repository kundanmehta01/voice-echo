// script.js
let mediaRecorder;
let recordedChunks = [];
let autoStream = false;
let micStream;
let isRecording = false;
let ws;
let usedWS = false;
let audioCtx;
let analyser;
let vuRAF;
let audioChunksArray = [];
let debugAudioBuffer = []; // For saving WAV

class AudioStreamPlayer {
    constructor() {
        this.audioContext = null;
        this.audioQueue = [];
        this.isPlaying = false;
        this.nextStartTime = 0;
        this.totalDuration = 0;
        this.chunksPlayed = 0;
        this.chunksReceived = 0;
        this.sourceNodes = [];
        this.playbackStarted = false;
        this.minBufferSize = 2; // Increased for smoother playback
        this.singleAudioMode = false; // Allow multiple chunks for streaming
        this.maxBufferSize = 8; // Prevent excessive buffering
        this.bufferTimeOffset = 0.1; // Small delay to ensure smooth scheduling
        this.failedChunks = new Set(); // Track failed chunks
        this.isComplete = false; // Track if all chunks received
        this.schedulingPrecision = 0.001; // High precision scheduling
        this.preloadDelay = 0.05; // Preload buffer time
    }

    async init() {
        if (!this.audioContext) {
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            console.log('🎵 Audio context initialized, sample rate:', this.audioContext.sampleRate);
        }
        return this.audioContext;
    }

    async decodeBase64Audio(base64Data) {
        try {
            const base64 = base64Data.replace(/^data:audio\/[a-z]+;base64,/, '');
            const binaryString = atob(base64);
            const bytes = new Uint8Array(binaryString.length);
            for (let i = 0; i < binaryString.length; i++) {
                bytes[i] = binaryString.charCodeAt(i);
            }
            const audioBuffer = await this.audioContext.decodeAudioData(bytes.buffer);
            return audioBuffer;
        } catch (error) {
            console.error('❌ Error decoding audio:', error);
            return null;
        }
    }

    async addChunk(base64Audio, chunkIndex) {
        if (!this.audioContext) {
            await this.init();
        }
        
        if (this.playbackStarted && this.singleAudioMode) {
            console.log('⚠️ Ignoring duplicate audio chunk in single audio mode');
            return;
        }

        // Prevent buffer overflow
        if (this.audioQueue.length >= this.maxBufferSize) {
            console.log('⚠️ Buffer full, waiting for playback to catch up');
            return;
        }

        this.chunksReceived++;
        console.log(`🎵 Processing chunk ${chunkIndex || this.chunksReceived}`);
        
        const audioBuffer = await this.decodeBase64Audio(base64Audio);
        if (!audioBuffer) {
            console.error('❌ Failed to decode chunk', chunkIndex);
            this.failedChunks.add(chunkIndex || this.chunksReceived);
            // Don't return, continue processing other chunks
            return;
        }

        // Add chunk to queue with proper indexing
        const chunkData = {
            buffer: audioBuffer,
            index: chunkIndex || this.chunksReceived,
            duration: audioBuffer.duration,
            timestamp: this.audioContext.currentTime
        };
        
        this.audioQueue.push(chunkData);

        console.log(`✅ Chunk ${chunkData.index} added to queue:`);
        console.log(`   Duration: ${audioBuffer.duration.toFixed(3)}s`);
        console.log(`   Queue size: ${this.audioQueue.length}`);
        console.log(`   Buffered duration: ${this.getTotalBufferedDuration().toFixed(3)}s`);
        console.log(`   Failed chunks: ${this.failedChunks.size}`);

        // Smart buffering strategy
        if (!this.playbackStarted) {
            const bufferedTime = this.getTotalBufferedDuration();
            if (this.audioQueue.length >= this.minBufferSize || bufferedTime >= 0.5) {
                console.log('🎵 Starting seamless playback:', {
                    chunks: this.audioQueue.length,
                    bufferedTime: bufferedTime.toFixed(3) + 's'
                });
                this.startPlayback();
            }
        } else {
            // If playback is running but buffer is low, add a slight delay to prevent gaps
            if (this.audioQueue.length === 1 && this.isPlaying) {
                console.log('⚡ Low buffer detected, optimizing timing');
            }
        }
    }

    getTotalBufferedDuration() {
        return this.audioQueue.reduce((total, chunk) => total + chunk.duration, 0);
    }

    startPlayback() {
        if (this.playbackStarted || this.audioQueue.length === 0) {
            return;
        }

        this.playbackStarted = true;
        // Start with a minimal delay for better scheduling precision
        this.nextStartTime = this.audioContext.currentTime + this.preloadDelay;
        console.log(`🎵 Playback scheduled to start at: ${this.nextStartTime.toFixed(3)}s`);
        this.playNextChunk();
    }

    playNextChunk() {
        if (this.audioQueue.length === 0) {
            console.log('📭 No more chunks in queue');
            this.isPlaying = false;
            
            // Check if we should wait for more chunks or if playback is complete
            if (!this.isComplete) {
                setTimeout(() => {
                    if (this.audioQueue.length > 0) {
                        console.log('🔄 Resuming playback with new chunks');
                        this.playNextChunk();
                    }
                }, 100); // Small delay to wait for potential new chunks
            } else {
                const status = document.getElementById('uploadStatus');
                if (status) {
                    status.textContent = `🔊 Playback complete (${this.chunksPlayed} chunks played)`;
                    status.className = 'status-text success';
                }
                this.playbackStarted = false;
            }
            return;
        }

        const chunk = this.audioQueue.shift();
        this.isPlaying = true;
        this.chunksPlayed++;

        const source = this.audioContext.createBufferSource();
        source.buffer = chunk.buffer;
        source.connect(this.audioContext.destination);

        // Ensure seamless timing - use precise scheduling
        const currentTime = this.audioContext.currentTime;
        const startTime = Math.max(this.nextStartTime, currentTime + this.schedulingPrecision);
        
        // Handle potential timing gaps
        if (startTime > this.nextStartTime + 0.01) {
            console.log(`⚡ Timing gap detected: ${(startTime - this.nextStartTime).toFixed(3)}s`);
        }
        
        source.start(startTime);

        console.log(`🔊 Playing chunk ${chunk.index}:`);
        console.log(`   Current time: ${currentTime.toFixed(3)}s`);
        console.log(`   Scheduled start: ${startTime.toFixed(3)}s`);
        console.log(`   Duration: ${chunk.duration.toFixed(3)}s`);
        console.log(`   Queue remaining: ${this.audioQueue.length}`);
        console.log(`   Timing precision: ${(startTime - this.nextStartTime).toFixed(3)}s`);

        const status = document.getElementById('uploadStatus');
        if (status) {
            const bufferedTime = this.getTotalBufferedDuration();
            status.textContent = `🔊 Playing ${this.chunksPlayed}/${this.chunksReceived} (${bufferedTime.toFixed(1)}s buffered)`;
            status.className = 'status-text success';
        }

        // Calculate next start time for seamless playback
        this.nextStartTime = startTime + chunk.duration;
        this.totalDuration += chunk.duration;

        // Schedule next chunk slightly early to prevent gaps
        const scheduleNext = () => {
            if (this.audioQueue.length > 0) {
                this.playNextChunk();
            } else if (!this.isComplete) {
                // Wait a bit for more chunks if stream isn't complete
                setTimeout(() => {
                    if (this.audioQueue.length > 0) {
                        this.playNextChunk();
                    } else {
                        this.isPlaying = false;
                    }
                }, 50);
            } else {
                this.isPlaying = false;
                this.playbackStarted = false;
                console.log('🎵 Stream playback complete');
            }
        };

        source.onended = () => {
            console.log(`✅ Chunk ${chunk.index} finished at ${this.audioContext.currentTime.toFixed(3)}s`);
            this.sourceNodes = this.sourceNodes.filter(s => s !== source);
            scheduleNext();
        };

        // Also schedule based on timing to ensure continuity
        const timeUntilNext = (startTime + chunk.duration - this.audioContext.currentTime) * 1000;
        if (timeUntilNext > 0) {
            setTimeout(scheduleNext, Math.max(0, timeUntilNext - 50)); // Schedule 50ms before end
        }

        this.sourceNodes.push(source);
    }

    // Mark stream as complete (no more chunks coming)
    markComplete() {
        this.isComplete = true;
        console.log('✅ Audio stream marked as complete');
        // If we have queued chunks, let them play out
        if (this.audioQueue.length === 0 && !this.isPlaying) {
            this.playbackStarted = false;
            const status = document.getElementById('uploadStatus');
            if (status) {
                status.textContent = `🎉 Stream complete (${this.chunksPlayed}/${this.chunksReceived} chunks played)`;
                status.className = 'status-text success';
            }
        }
    }

    // Retry failed chunk
    async retryFailedChunk(base64Audio, chunkIndex) {
        console.log(`🔄 Retrying chunk ${chunkIndex}`);
        this.failedChunks.delete(chunkIndex);
        await this.addChunk(base64Audio, chunkIndex);
    }

    // Handle audio decode errors gracefully
    handleDecodeError(chunkIndex, error) {
        console.error(`❌ Audio decode error for chunk ${chunkIndex}:`, error);
        this.failedChunks.add(chunkIndex);
        
        // Continue playing other chunks
        if (this.playbackStarted && this.audioQueue.length > 0) {
            console.log('⚡ Continuing playback despite decode error');
        }
        
        // Update UI to show error
        const status = document.getElementById('uploadStatus');
        if (status && this.failedChunks.size > 0) {
            status.textContent = `⚠️ Playing with ${this.failedChunks.size} failed chunks`;
            status.className = 'status-text warning';
        }
    }

    reset() {
        this.sourceNodes.forEach(source => {
            try {
                source.stop();
            } catch (e) {}
        });
        this.audioQueue = [];
        this.sourceNodes = [];
        this.isPlaying = false;
        this.playbackStarted = false;
        this.nextStartTime = 0;
        this.totalDuration = 0;
        this.chunksPlayed = 0;
        this.chunksReceived = 0;
        this.failedChunks.clear();
        this.isComplete = false;
        console.log('🔄 Audio player reset');
    }

    getStats() {
        return {
            chunksReceived: this.chunksReceived,
            chunksPlayed: this.chunksPlayed,
            queueLength: this.audioQueue.length,
            isPlaying: this.isPlaying,
            totalDuration: this.totalDuration.toFixed(2),
            bufferedDuration: this.getTotalBufferedDuration().toFixed(2)
        };
    }
}

let audioPlayer = new AudioStreamPlayer();

function getOrCreateSessionId() {
    const url = new URL(window.location.href);
    let session = url.searchParams.get('session');
    if (!session) {
        session = crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2);
        url.searchParams.set('session', session);
        window.history.replaceState({}, '', url.toString());
    }
    return session;
}

// Save PCM data as WAV for debugging
function saveDebugWav(pcmData) {
    const sampleRate = 16000;
    const numChannels = 1;
    const bitsPerSample = 16;
    const byteRate = sampleRate * numChannels * bitsPerSample / 8;
    const blockAlign = numChannels * bitsPerSample / 8;
    const dataSize = pcmData.length * 2;

    const buffer = new ArrayBuffer(44 + dataSize);
    const view = new DataView(buffer);

    // RIFF header
    writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + dataSize, true);
    writeString(view, 8, 'WAVE');

    // fmt chunk
    writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true); // Chunk size
    view.setUint16(20, 1, true); // PCM format
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, byteRate, true);
    view.setUint16(32, blockAlign, true);
    view.setUint16(34, bitsPerSample, true);

    // data chunk
    writeString(view, 36, 'data');
    view.setUint32(40, dataSize, true);

    // Write PCM data
    for (let i = 0; i < pcmData.length; i++) {
        view.setInt16(44 + i * 2, pcmData[i], true);
    }

    const blob = new Blob([buffer], { type: 'audio/wav' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `debug_audio_${Date.now()}.wav`;
    a.click();
    URL.revokeObjectURL(url);
    console.log('💾 Saved debug WAV file');
}

function writeString(view, offset, string) {
    for (let i = 0; i < string.length; i++) {
        view.setUint8(offset + i, string.charCodeAt(i));
    }
}

async function toggleRecording() {
    const btn = document.getElementById('recordBtn');
    const label = document.getElementById('recordLabel');
    const status = document.getElementById('uploadStatus');
    const bubble = document.getElementById('chatBubble');

    if (!btn || !label || !status || !bubble) {
        console.error('Required elements missing:', {
            recordBtn: !!btn,
            recordLabel: !!label,
            uploadStatus: !!status,
            chatBubble: !!bubble
        });
        if (status) {
            status.textContent = '❌ UI initialization error: Missing elements';
            status.className = 'status-text error';
        }
        return;
    }

    if (!isRecording) {
        recordedChunks = [];
        audioChunksArray = [];
        debugAudioBuffer = []; // Reset debug buffer
        audioPlayer.reset();
        btn.classList.add('recording');
        btn.setAttribute('aria-pressed', 'true');
        label.textContent = 'Listening... Tap to stop';
        status.textContent = '🎤 Listening...';
        status.className = 'status-text pending';

        try {
            micStream = await navigator.mediaDevices.getUserMedia({ audio: { sampleRate: 48000, channelCount: 1 } });
            startVU(micStream);

            ws = new WebSocket(`ws://${window.location.host}/ws`);
            ws.binaryType = 'arraybuffer';

            ws.onmessage = async (ev) => {
                try {
                    console.log('WebSocket message received:', ev.data);
                    const message = JSON.parse(ev.data);

                    if (message.type === 'transcript') {
                        bubble.style.display = 'block';
                        const bubbleUser = document.getElementById('bubbleUser');
                        if (!bubbleUser) {
                            console.error('bubbleUser element not found');
                            status.textContent = '❌ UI error: Missing bubbleUser';
                            status.className = 'status-text error';
                            return;
                        }
                        bubbleUser.textContent = message.text;
                        if (message.end_of_turn || message.is_final) {
                            console.log('🔚 Final transcript received:', message.text);
                            bubbleUser.style.fontWeight = '600';
                            bubbleUser.style.color = '#1a1a1a';
                            bubbleUser.style.fontStyle = 'normal';
                            status.textContent = '✅ Turn complete - transcript finalized';
                            status.className = 'status-text success';
                            bubble.classList.add('turn-complete');
                            setTimeout(() => bubble.classList.remove('turn-complete'), 1500);
                        } else {
                            console.log('📝 Interim transcript:', message.text);
                            bubbleUser.style.fontWeight = '400';
                            bubbleUser.style.color = '#666';
                            bubbleUser.style.fontStyle = 'italic';
                            status.textContent = '🎤 Listening...';
                            status.className = 'status-text pending';
                        }
                    } else if (message.type === 'tts_audio') {
                        audioChunksArray.push(message.audio_base64);
                        console.log('✅ Audio chunk received and accumulated:');
                        console.log(`  - Chunk index: ${message.chunk_index || audioChunksArray.length}`);
                        console.log(`  - Base64 length: ${message.audio_base64.length} characters`);
                        console.log(`  - Total chunks accumulated: ${audioChunksArray.length}`);
                        console.log(`  - Preview: ${message.audio_base64.substring(0, 50)}...`);
                        await audioPlayer.addChunk(message.audio_base64, message.chunk_index);
                        const stats = audioPlayer.getStats();
                        status.textContent = `🔊 Streaming audio... (${stats.chunksReceived} received, ${stats.chunksPlayed} played)`;
                        status.className = 'status-text success';
                    } else if (message.type === 'llm_start') {
                        console.log('🤖 LLM processing started:', message.message);
                        status.textContent = message.message;
                        status.className = 'status-text pending';
                    } else if (message.type === 'llm_chunk') {
                        console.log('📝 LLM chunk received:', message.text);
                        const bubbleAI = document.getElementById('bubbleAI');
                        if (!bubbleAI) {
                            console.error('bubbleAI element not found');
                            status.textContent = '❌ UI error: Missing bubbleAI';
                            status.className = 'status-text error';
                            return;
                        }
                        bubbleAI.textContent += message.text;
                    } else if (message.type === 'llm_complete') {
                        console.log('✅ LLM response complete:', message.full_response);
                        console.log('📊 Total audio chunks accumulated:', audioChunksArray.length);
                        const bubbleAI = document.getElementById('bubbleAI');
                        if (bubbleAI) {
                            bubbleAI.textContent = message.full_response;
                        }
                    } else if (message.type === 'error') {
                        console.error('Error message from server:', message.message);
                        status.textContent = '❌ ' + message.message;
                        status.className = 'status-text error';
                    }
                } catch (e) {
                    console.error('Error processing WebSocket message:', e);
                    console.error('Raw message data:', ev.data);
                    status.textContent = '❌ WebSocket message error';
                    status.className = 'status-text error';
                }
            };

            ws.onopen = () => {
                console.log('[WS] Connected');
            };

            ws.onerror = () => {
                console.error('[WS] Error');
                status.textContent = '❌ WebSocket error';
                status.className = 'status-text error';
            };

            audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 48000 });
            const source = audioCtx.createMediaStreamSource(micStream);
            const processor = audioCtx.createScriptProcessor(4096, 1, 1); // Revert to 4096 for 8192 bytes after downsampling

            const TARGET_SR = 16000;
            function floatTo16BitPCM(float32Array) {
                const out = new Int16Array(float32Array.length);
                for (let i = 0; i < float32Array.length; i++) {
                    let s = Math.max(-1, Math.min(1, float32Array[i] * 10.0)); // Increased gain
                    out[i] = (s < 0 ? s * 0x8000 : s * 0x7FFF) | 0;
                }
                console.log('PCM data sample:', out.slice(0, 10), 'Mean abs:', Math.round(out.reduce((sum, v) => sum + Math.abs(v), 0) / out.length));
                debugAudioBuffer.push(...out); // Collect for WAV
                return out;
            }
            function downsample(buffer, inSampleRate, outSampleRate) {
                const sampleRateRatio = inSampleRate / outSampleRate;
                const newLength = Math.round(buffer.length / sampleRateRatio);
                const result = new Float32Array(newLength);
                let offsetResult = 0;
                let offsetBuffer = 0;
                while (offsetResult < result.length) {
                    const nextOffsetBuffer = Math.round((offsetResult + 1) * sampleRateRatio);
                    let accum = 0, count = 0;
                    for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
                        accum += buffer[i];
                        count++;
                    }
                    result[offsetResult] = accum / (count || 1);
                    offsetResult++;
                    offsetBuffer = nextOffsetBuffer;
                }
                console.log('Downsampled data sample:', result.slice(0, 10), 'Mean abs:', Math.round(result.reduce((sum, v) => sum + Math.abs(v), 0) / result.length));
                return result;
            }

            processor.onaudioprocess = (e) => {
                try {
                    if (!ws || ws.readyState !== WebSocket.OPEN) return;
                    const input = e.inputBuffer.getChannelData(0);
                    console.log('Raw input sample:', input.slice(0, 10), 'Mean abs:', input.reduce((sum, v) => sum + Math.abs(v), 0) / input.length);
                    const ds = downsample(input, audioCtx.sampleRate, TARGET_SR);
                    const pcm16 = floatTo16BitPCM(ds);
                    if (pcm16.length !== 4096) {
                        console.warn(`Unexpected PCM length: ${pcm16.length}, expected 4096`);
                    }
                    ws.send(pcm16.buffer);
                    usedWS = true;
                    console.log(`Sending audio chunk: ${pcm16.buffer.byteLength} bytes`);
                } catch (e) {
                    console.error('Error processing audio:', e);
                }
            };

            source.connect(processor);
            processor.connect(audioCtx.destination);

            isRecording = true;
        } catch (error) {
            console.error('Microphone access error:', error);
            alert('Microphone access error: ' + error.message);
            btn.classList.remove('recording');
            btn.setAttribute('aria-pressed', 'false');
            label.textContent = 'Start Recording';
            status.textContent = '❌ Microphone access error';
            status.className = 'status-text error';
            isRecording = false;
        }
    } else {
        try {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({"type": "end"}));
            }
            if (ws) ws.close();
            if (micStream) micStream.getTracks().forEach(t => t.stop());
            stopVU();
            if (audioCtx) audioCtx.close();
            if (debugAudioBuffer.length > 0) {
                saveDebugWav(new Int16Array(debugAudioBuffer));
            }
        } catch (e) {
            console.error('Error stopping recording:', e);
        }
        isRecording = false;
        btn.classList.remove('recording');
        btn.setAttribute('aria-pressed', 'false');
        label.textContent = 'Start Recording';
        status.textContent = '✅ Recording stopped';
        status.className = 'status-text success';
        const stats = audioPlayer.getStats();
        console.log('📊 Final Audio Stats:');
        console.log(`   Chunks received: ${stats.chunksReceived}`);
        console.log(`   Chunks played: ${stats.chunksPlayed}`);
        console.log(`   Total duration: ${stats.totalDuration}s`);
    }
}

function startVU(stream) {
    try {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const src = audioCtx.createMediaStreamSource(stream);
        analyser = audioCtx.createAnalyser();
        analyser.fftSize = 1024;
        src.connect(analyser);
        const vu = document.querySelector('.vu');
        if (!vu) {
            console.warn('VU meter element not found');
            return;
        }
        const bars = vu.querySelectorAll('.bar');
        const data = new Uint8Array(analyser.frequencyBinCount);
        const update = () => {
            analyser.getByteTimeDomainData(data);
            let sum = 0;
            for (let i = 0; i < data.length; i++) {
                const v = (data[i] - 128) / 128;
                sum += v * v;
            }
            const rms = Math.sqrt(sum / data.length);
            const h = Math.min(1, rms * 3);
            bars.forEach((b, idx) => {
                const factor = 0.7 + idx * 0.15;
                b.style.setProperty('--vu', `${Math.max(6, Math.floor(h * 36 * factor))}px`);
            });
            vuRAF = requestAnimationFrame(update);
        };
        vuRAF = requestAnimationFrame(update);
    } catch (e) {
        console.error('Error starting VU meter:', e);
    }
}

function stopVU() {
    try {
        if (vuRAF) cancelAnimationFrame(vuRAF);
    } catch (e) {}
    const bars = document.querySelectorAll('.vu .bar');
    bars.forEach(b => b.style.setProperty('--vu', '8px'));
    try {
        if (audioCtx) audioCtx.close();
    } catch (e) {}
    audioCtx = null;
    analyser = null;
    vuRAF = null;
}

async function refreshHistory() {
    const sessionId = getOrCreateSessionId();
    try {
        const res = await fetch(`/agent/chat/${encodeURIComponent(sessionId)}`);
        const data = await res.json();
        const list = document.getElementById('transcriptDisplay');
        if (!list) {
            console.error('transcriptDisplay element not found in DOM');
            return;
        }
        list.innerHTML = '';
        const fmt = (ts) => {
            try {
                return new Date(ts).toLocaleTimeString();
            } catch {
                return '';
            }
        };
        (data.chat_history || []).forEach((msg, index) => {
            const row = document.createElement('div');
            row.className = `msg ${msg.role}`;
            row.innerHTML = `
                <div class="avatar">${msg.role === 'user' ? '🧑' : '🤖'}</div>
                <div class="bubble">
                    <div class="meta">
                        <span class="name">${msg.role === 'user' ? 'You' : 'AI Assistant'}</span>
                        <span class="time">${fmt(msg.ts)}</span>
                        <button class="icon-btn" title="Copy" onclick="copyMsg(${index})"><i class="fas fa-copy"></i></button>
                    </div>
                    <div class="content">${msg.content || ''}</div>
                </div>
            `;
            list.appendChild(row);
        });
        scrollHistoryToBottom();
        window.__lastHistory = data.chat_history || [];
    } catch (e) {
        console.error('Error refreshing history:', e);
    }
}

function scrollHistoryToBottom() {
    const list = document.getElementById('transcriptDisplay');
    if (!list) {
        console.error('transcriptDisplay element not found for scrolling');
        return;
    }
    try {
        list.scrollTo({ top: list.scrollHeight, behavior: 'smooth' });
    } catch {
        list.scrollTop = list.scrollHeight;
    }
}

function scrollHistoryToTop() {
    const list = document.getElementById('transcriptDisplay');
    if (!list) {
        console.error('transcriptDisplay element not found for scrolling');
        return;
    }
    try {
        list.scrollTo({ top: 0, behavior: 'smooth' });
    } catch {
        list.scrollTop = 0;
    }
}

function copyMsg(index) {
    try {
        const msg = (window.__lastHistory || [])[index];
        if (!msg) return;
        navigator.clipboard.writeText(msg.content || '');
    } catch (e) {
        console.error('Error copying message:', e);
    }
}

async function clearHistory() {
    const sessionId = getOrCreateSessionId();
    try {
        await fetch(`/agent/chat/${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
        await refreshHistory();
        const status = document.getElementById('uploadStatus');
        if (status) {
            status.textContent = '✅ Chat history cleared';
            status.className = 'status-text success';
        }
    } catch (e) {
        console.error('Error clearing history:', e);
        const status = document.getElementById('uploadStatus');
        if (status) {
            status.textContent = '❌ Error clearing history';
            status.className = 'status-text error';
        }
    }
}

function toggleAutoStream() {
    autoStream = !autoStream;
    const btn = document.getElementById('autoToggle');
    if (btn) {
        btn.textContent = autoStream ? 'Disable Auto-Stream' : 'Enable Auto-Stream';
        btn.classList.toggle('btn-accent', autoStream);
    }
    console.log('Auto-Stream:', autoStream ? 'Enabled' : 'Disabled');
}

window.addEventListener('DOMContentLoaded', () => {
    getOrCreateSessionId();
    refreshHistory();
    const clearBtn = document.getElementById('clearChatBtn');
    if (clearBtn) {
        clearBtn.addEventListener('click', clearHistory);
    }
});