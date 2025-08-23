// static/audio-processor.js
class AudioProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this.buffer = [];
        this.targetSampleCount = 800; // 50 ms at 16 kHz
    }

    process(inputs, outputs, parameters) {
        const input = inputs[0];
        if (input.length > 0) {
            const inputData = input[0];
            this.buffer.push(...inputData);

            while (this.buffer.length >= this.targetSampleCount) {
                const chunk = this.buffer.slice(0, this.targetSampleCount);
                this.buffer = this.buffer.slice(this.targetSampleCount);

                const outputSampleRate = 16000;
                const ratio = sampleRate / outputSampleRate;
                const newLen = Math.round(chunk.length / ratio);
                const result = new Float32Array(newLen);
                let offsetResult = 0;
                let offsetBuffer = 0;
                while (offsetResult < newLen) {
                    const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
                    let accum = 0,
                        count = 0;
                    for (let i = offsetBuffer; i < nextOffsetBuffer && i < chunk.length; i++) {
                        accum += chunk[i];
                        count++;
                    }
                    result[offsetResult] = accum / (count || 1);
                    offsetResult++;
                    offsetBuffer = nextOffsetBuffer;
                }

                const output = new Int16Array(result.length);
                for (let i = 0; i < result.length; i++) {
                    const s = Math.max(-1, Math.min(1, result[i]));
                    output[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                }

                this.port.postMessage(output.buffer);
            }
        }
        return true;
    }
}

registerProcessor("audio-processor", AudioProcessor);