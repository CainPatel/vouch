class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetRate = 16000;
    this.ratio = sampleRate / this.targetRate;
    this.readPos = 0;
    this.frameSize = 960; // 60ms at 16kHz
    this.outBuf = new Int16Array(this.frameSize);
    this.outIdx = 0;
    this.muted = false;
    this.active = false;

    this.port.onmessage = (ev) => {
      if (!ev.data) return;
      if (typeof ev.data.muted === "boolean") {
        this.muted = ev.data.muted;
      }
      if (typeof ev.data.active === "boolean") {
        this.active = ev.data.active;
      }
    };
  }

  process(inputs) {
    if (!this.active) {
      return true;
    }
    const input = inputs[0];
    const ch0 = input && input[0] && input[0].length > 0 ? input[0] : null;
    const len = ch0 ? ch0.length : 128;

    while (this.readPos < len) {
      const idx = Math.floor(this.readPos);
      let s = !ch0 || this.muted ? 0 : ch0[idx];
      if (s > 1) s = 1;
      else if (s < -1) s = -1;
      this.outBuf[this.outIdx++] = s < 0 ? s * 0x8000 : s * 0x7fff;

      if (this.outIdx >= this.frameSize) {
        const copy = new Int16Array(this.outBuf);
        this.port.postMessage(copy.buffer, [copy.buffer]);
        this.outIdx = 0;
      }
      this.readPos += this.ratio;
    }
    this.readPos -= len;
    return true;
  }
}

registerProcessor("pcm-capture-processor", PcmCaptureProcessor);
