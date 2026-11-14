class PcmPlaybackProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.inputRate = 24000;
    this.step = this.inputRate / sampleRate; // 24k samples consumed per output sample
    this.chunks = [];
    this.chunkIdx = 0;
    this.queuedSamples = 0;
    this.buffering = true;
    this.minPrebuffer = 720; // 30ms jitter buffer at 24kHz
    this.consumedSinceReport = 0;

    this.port.onmessage = (ev) => {
      const msg = ev.data;
      if (msg && msg.type === "flush") {
        this.chunks = [];
        this.chunkIdx = 0;
        this.queuedSamples = 0;
        this.buffering = true;
        return;
      }
      if (msg instanceof ArrayBuffer) {
        const int16 = new Int16Array(msg);
        if (int16.length > 0) {
          const f32 = new Float32Array(int16.length);
          for (let i = 0; i < int16.length; i++) {
            f32[i] = int16[i] / 32768.0;
          }
          this.chunks.push(f32);
          this.queuedSamples += f32.length;
          if (this.buffering && this.queuedSamples >= this.minPrebuffer) {
            this.buffering = false;
          }
        }
      }
    };
  }

  _sampleAt(offset) {
    let rem = offset;
    for (let c = 0; c < this.chunks.length; c++) {
      const arr = this.chunks[c];
      const avail = c === 0 ? arr.length - Math.floor(this.chunkIdx) : arr.length;
      if (rem < avail) {
        const base = c === 0 ? Math.floor(this.chunkIdx) + rem : rem;
        return arr[base];
      }
      rem -= avail;
    }
    return 0;
  }

  process(inputs, outputs) {
    const out = outputs[0][0];
    if (!out) return true;

    if (this.buffering || this.queuedSamples <= 0) {
      out.fill(0);
      if (this.queuedSamples <= 0) {
        this.buffering = true;
      }
      return true;
    }

    let consumed = 0;
    for (let i = 0; i < out.length; i++) {
      if (this.chunks.length === 0) {
        out[i] = 0;
        this.buffering = true;
        continue;
      }
      const curChunk = this.chunks[0];
      const i0 = Math.floor(this.chunkIdx);
      const frac = this.chunkIdx - i0;
      const s0 = curChunk[i0] || 0;
      let s1 = s0;
      if (i0 + 1 < curChunk.length) {
        s1 = curChunk[i0 + 1];
      } else if (this.chunks.length > 1) {
        s1 = this.chunks[1][0] || 0;
      }
      out[i] = s0 + (s1 - s0) * frac;

      this.chunkIdx += this.step;
      consumed += this.step;
      while (this.chunks.length > 0 && this.chunkIdx >= this.chunks[0].length) {
        const finished = this.chunks.shift();
        this.chunkIdx -= finished.length;
      }
      this.queuedSamples = Math.max(0, this.queuedSamples - this.step);
    }

    if (consumed > 0) {
      this.consumedSinceReport += consumed;
      if (this.consumedSinceReport >= 1200) {
        this.port.postMessage({
          type: "played",
          samples24k: this.consumedSinceReport,
        });
        this.consumedSinceReport = 0;
      }
    }
    return true;
  }
}

registerProcessor("pcm-playback-processor", PcmPlaybackProcessor);
