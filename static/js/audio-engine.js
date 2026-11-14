// Shared WebAudio engine for Caller page:
// - Captures live mic (with echo cancellation) AND scripted WAV clips through the SAME AudioWorklet -> 16kHz PCM -> WebSocket path
// - Plays incoming 24kHz PCM gaplessly via PcmPlaybackProcessor
// - Exposes AnalyserNodes + recording mix MediaStream for /demo waveforms & video recorder

export class CallerAudioEngine {
  constructor({ onPcm16kFrame, onClipEnded }) {
    this.onPcm16kFrame = onPcm16kFrame;
    this.onClipEnded = onClipEnded;
    this.ctx = null;
    this.micStream = null;
    this.micSource = null;
    this.inputBus = null;
    this.captureNode = null;
    this.playbackNode = null;
    this.callerAnalyser = null;
    this.assistantAnalyser = null;
    this.recordDest = null;
    this.activeClipSource = null;
    this.muted = false;
    this.pushToTalk = false;
    this.pttHeld = false;

    this.stats = {
      receivedBytes: 0,
      receivedSeconds: 0,
      playedSeconds: 0,
      postTapMarked: false,
      postTapReceivedBytes: 0,
      postTapReceivedSeconds: 0,
      postTapPlayedSeconds: 0,
    };
    window.__vouchAudioStats = this.stats;
  }

  async init({ enableMic = true } = {}) {
    if (!this.ctx) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AudioCtx();
      await this.ctx.audioWorklet.addModule("/static/js/pcm-capture-worklet.js");
      await this.ctx.audioWorklet.addModule("/static/js/pcm-playback-worklet.js");

      this.inputBus = this.ctx.createGain();
      this.callerAnalyser = this.ctx.createAnalyser();
      this.callerAnalyser.fftSize = 128;
      this.assistantAnalyser = this.ctx.createAnalyser();
      this.assistantAnalyser.fftSize = 128;
      this.recordDest = this.ctx.createMediaStreamDestination();

      this.captureNode = new AudioWorkletNode(this.ctx, "pcm-capture-processor");
      this.captureNode.port.onmessage = (ev) => {
        if (ev.data instanceof ArrayBuffer && this.onPcm16kFrame) {
          this.onPcm16kFrame(ev.data);
        }
      };

      this.inputBus.connect(this.callerAnalyser);
      this.inputBus.connect(this.captureNode);
      this.inputBus.connect(this.recordDest); // Include caller voice in demo recording mix

      this.playbackNode = new AudioWorkletNode(this.ctx, "pcm-playback-processor");
      this.playbackNode.port.onmessage = (ev) => {
        if (ev.data && ev.data.type === "played") {
          const sec = ev.data.samples24k / 24000;
          this.stats.playedSeconds += sec;
          if (this.stats.postTapMarked) {
            this.stats.postTapPlayedSeconds += sec;
          }
        }
      };
      this.playbackNode.connect(this.assistantAnalyser);
      this.assistantAnalyser.connect(this.ctx.destination);
      this.assistantAnalyser.connect(this.recordDest); // Include assistant voice in demo recording mix
    }

    if (this.ctx.state === "suspended") {
      await this.ctx.resume();
    }

    if (enableMic && !this.micStream) {
      try {
        this.micStream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
            channelCount: 1,
          },
          video: false,
        });
        this.micSource = this.ctx.createMediaStreamSource(this.micStream);
        this.micSource.connect(this.inputBus);
      } catch (err) {
        console.warn("Microphone unavailable (continuing with scripted clips/text):", err);
      }
    }
    this._syncMuteState();
    if (this.captureNode) {
      this.captureNode.port.postMessage({ active: true });
    }
  }

  resetStats() {
    this.stats.receivedBytes = 0;
    this.stats.receivedSeconds = 0;
    this.stats.playedSeconds = 0;
    this.stats.postTapMarked = false;
    this.stats.postTapReceivedBytes = 0;
    this.stats.postTapReceivedSeconds = 0;
    this.stats.postTapPlayedSeconds = 0;
  }

  markVerificationAnswered() {
    this.stats.postTapMarked = true;
    this.stats.postTapReceivedBytes = 0;
    this.stats.postTapReceivedSeconds = 0;
    this.stats.postTapPlayedSeconds = 0;
  }

  enqueueAssistantPcm24k(arrayBuffer) {
    if (!this.playbackNode) return;
    const byteLen = arrayBuffer.byteLength;
    const sec = byteLen / (24000 * 2);
    this.stats.receivedBytes += byteLen;
    this.stats.receivedSeconds += sec;
    if (this.stats.postTapMarked) {
      this.stats.postTapReceivedBytes += byteLen;
      this.stats.postTapReceivedSeconds += sec;
    }
    const copy = arrayBuffer.slice(0);
    this.playbackNode.port.postMessage(copy, [copy]);
  }

  flushAssistantPlayback() {
    if (this.playbackNode) {
      this.playbackNode.port.postMessage({ type: "flush" });
    }
  }

  setMuted(muted) {
    this.muted = muted;
    this._syncMuteState();
  }

  setPushToTalk(enabled) {
    this.pushToTalk = enabled;
    this._syncMuteState();
  }

  setPttHeld(held) {
    this.pttHeld = held;
    this._syncMuteState();
  }

  _syncMuteState() {
    if (!this.captureNode) return;
    const effectiveMuted = this.muted || (this.pushToTalk && !this.pttHeld);
    this.captureNode.port.postMessage({ muted: effectiveMuted });
  }

  async playScriptedClip(url) {
    await this.init({ enableMic: false });
    if (this.activeClipSource) {
      try {
        this.activeClipSource.stop();
      } catch (_) {}
      this.activeClipSource = null;
    }
    // Temporarily unmute capture worklet while clip plays
    if (this.captureNode) {
      this.captureNode.port.postMessage({ muted: false });
    }

    const resp = await fetch(url);
    if (!resp.ok) {
      throw new Error(`Clip not found: ${url}`);
    }
    const raw = await resp.arrayBuffer();
    const audioBuf = await this.ctx.decodeAudioData(raw);
    const src = this.ctx.createBufferSource();
    src.buffer = audioBuf;
    // Feed into inputBus (drives capture worklet -> server AND waveform) AND local speakers softly so presenter hears it
    src.connect(this.inputBus);
    const monitorGain = this.ctx.createGain();
    monitorGain.gain.value = 0.85;
    src.connect(monitorGain);
    monitorGain.connect(this.ctx.destination);

    this.activeClipSource = src;
    return new Promise((resolve) => {
      src.onended = () => {
        if (this.activeClipSource === src) {
          this.activeClipSource = null;
        }
        this._syncMuteState();
        if (this.onClipEnded) this.onClipEnded();
        resolve();
      };
      src.start();
    });
  }

  getLevels() {
    const readBins = (analyser) => {
      if (!analyser) return new Array(16).fill(0);
      const data = new Uint8Array(analyser.frequencyBinCount);
      analyser.getByteFrequencyData(data);
      const out = [];
      const step = Math.max(1, Math.floor(data.length / 16));
      for (let i = 0; i < 16; i++) {
        out.push(Math.round((data[i * step] / 255) * 100) / 100);
      }
      return out;
    };
    return {
      callerBins: readBins(this.callerAnalyser),
      assistantBins: readBins(this.assistantAnalyser),
    };
  }

  stopMic() {
    if (this.captureNode) {
      this.captureNode.port.postMessage({ active: false });
    }
    if (this.activeClipSource) {
      try {
        this.activeClipSource.stop();
      } catch (_) {}
      this.activeClipSource = null;
    }
    if (this.micStream) {
      for (const t of this.micStream.getTracks()) {
        t.stop();
      }
      this.micStream = null;
    }
    if (this.micSource) {
      try {
        this.micSource.disconnect();
      } catch (_) {}
      this.micSource = null;
    }
    this.flushAssistantPlayback();
  }
}
