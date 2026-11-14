// Shared WebAudio engine for Caller page:
// - Captures live mic (pinned to macOS "default" input with echo cancellation) AND scripted WAV clips
//   through the SAME AudioWorklet -> 16kHz PCM -> WebSocket path
// - Plays incoming 24kHz PCM gaplessly via native scheduled AudioBufferSourceNodes (stereo-safe across sample rates)
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
    this.callerAnalyser = null;
    this.assistantAnalyser = null;
    this.recordDest = null;
    this.activeClipSource = null;
    this.scheduledSources = new Set();
    this.nextPlayTime = 0;
    this.recordingActive = false;
    this.preferredDeviceId = "";
    this.activeMicLabel = "";
    this.lastMicError = "";
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

  async _ensureAudioGraph() {
    if (!this.ctx || this.ctx.state === "closed") {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AudioCtx({ latencyHint: "interactive" });
      // Resume synchronously on user gesture tick before any await
      if (this.ctx.state === "suspended") {
        this.ctx.resume().catch(() => {});
      }
      if (typeof this.ctx.setSinkId === "function") {
        this.ctx.setSinkId("").catch(() => {});
      }

      await this.ctx.audioWorklet.addModule("/static/js/pcm-capture-worklet.js?v=2");

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
      const silentSink = this.ctx.createGain();
      silentSink.gain.value = 0;
      this.captureNode.connect(silentSink);
      silentSink.connect(this.ctx.destination);
      this.inputBus.connect(this.recordDest); // Include caller voice in demo recording mix

      this.assistantAnalyser.connect(this.ctx.destination);
      this.assistantAnalyser.connect(this.recordDest); // Include assistant voice in demo recording mix
      this.nextPlayTime = 0;
    }

    if (this.ctx.state !== "running") {
      await this.ctx.resume().catch(() => {});
    }
  }

  async _openBestMicrophone() {
    this.lastMicError = "";
    const baseAudio = {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      channelCount: 1,
    };

    const firstConstraints = this.preferredDeviceId
      ? { audio: { ...baseAudio, deviceId: { exact: this.preferredDeviceId } }, video: false }
      : { audio: baseAudio, video: false };

    let stream = await navigator.mediaDevices.getUserMedia(firstConstraints);

    // If user didn't manually pick a device, check if macOS Continuity Camera ("iPhone"/"iPad") hijacked the mic
    if (!this.preferredDeviceId && navigator.mediaDevices.enumerateDevices) {
      const currentTrack = stream.getAudioTracks()[0];
      const currentLabel = (currentTrack && currentTrack.label ? currentTrack.label : "").toLowerCase();
      const isContinuity =
        currentLabel.includes("iphone") ||
        currentLabel.includes("ipad") ||
        currentLabel.includes("continuity");

      if (isContinuity) {
        try {
          const devices = await navigator.mediaDevices.enumerateDevices();
          const audioInputs = devices.filter(
            (d) =>
              d.kind === "audioinput" &&
              d.deviceId &&
              d.deviceId !== "default" &&
              d.deviceId !== "communications"
          );
          const nonContinuity = audioInputs.filter((d) => {
            const lbl = (d.label || "").toLowerCase();
            return !lbl.includes("iphone") && !lbl.includes("ipad") && !lbl.includes("continuity");
          });
          // Prefer headphones/AirPods/USB first, otherwise built-in MacBook mic
          const best =
            nonContinuity.find((d) => !d.label.toLowerCase().includes("macbook")) ||
            nonContinuity[0];
          if (best) {
            for (const t of stream.getTracks()) t.stop();
            stream = await navigator.mediaDevices.getUserMedia({
              audio: { ...baseAudio, deviceId: { exact: best.deviceId } },
              video: false,
            });
            this.preferredDeviceId = best.deviceId;
          }
        } catch (swapErr) {
          console.warn("Could not swap away from Continuity mic:", swapErr);
        }
      }
    }

    const activeTrack = stream.getAudioTracks()[0];
    this.activeMicLabel = activeTrack ? activeTrack.label || "Active Microphone" : "";
    return stream;
  }

  async listMicrophones() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return [];
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      return devices.filter((d) => d.kind === "audioinput" && d.deviceId);
    } catch {
      return [];
    }
  }

  async switchMicrophone(deviceId) {
    this.preferredDeviceId = deviceId || "";
    if (this.micStream) {
      for (const t of this.micStream.getTracks()) t.stop();
      this.micStream = null;
    }
    if (this.micSource) {
      try {
        this.micSource.disconnect();
      } catch (_) {}
      this.micSource = null;
    }
    if (this.ctx) {
      await this.init({ enableMic: true });
    }
  }

  async init({ enableMic = true } = {}) {
    // Acquire mic FIRST when requested so macOS CoreAudio switches input profile BEFORE binding AudioContext output sink
    if (enableMic && !this.micStream) {
      try {
        this.micStream = await this._openBestMicrophone();
      } catch (err) {
        this.lastMicError = err && err.message ? err.message : String(err);
        console.warn("Microphone unavailable (continuing with scripted clips/text):", err);
      }
    }

    await this._ensureAudioGraph();

    if (enableMic && this.micStream && !this.micSource) {
      try {
        this.micSource = this.ctx.createMediaStreamSource(this.micStream);
        this.micSource.connect(this.inputBus);
      } catch (err) {
        console.warn("Could not attach mic source:", err);
      }
    }

    // Resume again after getUserMedia in case macOS CoreAudio suspended context during device activation
    if (this.ctx && this.ctx.state !== "running") {
      await this.ctx.resume().catch(() => {});
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
    if (!this.ctx || !this.assistantAnalyser) return;
    if (this.ctx.state !== "running") {
      this.ctx.resume().catch(() => {});
    }

    const evenLen = arrayBuffer.byteLength & ~1;
    if (evenLen <= 0) return;

    const sampleCount = evenLen >> 1;
    const sec = sampleCount / 24000;
    const isPostTapChunk = this.stats.postTapMarked;

    this.stats.receivedBytes += evenLen;
    this.stats.receivedSeconds += sec;
    if (isPostTapChunk) {
      this.stats.postTapReceivedBytes += evenLen;
      this.stats.postTapReceivedSeconds += sec;
    }

    const int16 = new Int16Array(arrayBuffer, 0, sampleCount);
    const audioBuf = this.ctx.createBuffer(1, sampleCount, 24000);
    const ch0 = audioBuf.getChannelData(0);
    for (let i = 0; i < sampleCount; i++) {
      ch0[i] = int16[i] / 32768.0;
    }

    const src = this.ctx.createBufferSource();
    src.buffer = audioBuf;
    src.connect(this.assistantAnalyser);

    const now = this.ctx.currentTime;
    const startAt = Math.max(now + 0.015, this.nextPlayTime);
    this.nextPlayTime = startAt + audioBuf.duration;

    this.scheduledSources.add(src);
    let accounted = false;
    const creditPlayed = (dur) => {
      if (accounted) return;
      accounted = true;
      this.stats.playedSeconds += dur;
      if (isPostTapChunk || this.stats.postTapMarked) {
        this.stats.postTapPlayedSeconds += dur;
      }
    };

    src.onended = () => {
      this.scheduledSources.delete(src);
      creditPlayed(sec);
    };

    src.start(startAt);
  }

  flushAssistantPlayback() {
    for (const src of Array.from(this.scheduledSources)) {
      try {
        src.onended = null;
        src.stop();
        src.disconnect();
      } catch (_) {}
    }
    this.scheduledSources.clear();
    this.nextPlayTime = this.ctx ? this.ctx.currentTime : 0;
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
    if (this.ctx && this.ctx.state !== "running") {
      await this.ctx.resume().catch(() => {});
    }
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
    // Feed into inputBus (drives capture worklet -> server AND waveform) AND local speakers so presenter hears it
    src.connect(this.inputBus);
    const monitorGain = this.ctx.createGain();
    monitorGain.gain.value = 0.9;
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

  stopMic({ flushPlayback = false } = {}) {
    if (this.captureNode) {
      this.captureNode.port.postMessage({ active: false });
    }
    if (this.activeClipSource) {
      try {
        this.activeClipSource.stop();
      } catch (_) {}
      this.activeClipSource = null;
    }
    const hadMic = Boolean(this.micStream);
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
    if (flushPlayback) {
      this.flushAssistantPlayback();
    }
    // Reset AudioContext after mic teardown on macOS so VoiceProcessingIO/Continuity profile switches never leave a dead output sink
    if (hadMic && !this.recordingActive && this.ctx && this.scheduledSources.size === 0) {
      const oldCtx = this.ctx;
      this.ctx = null;
      this.inputBus = null;
      this.captureNode = null;
      this.callerAnalyser = null;
      this.assistantAnalyser = null;
      this.recordDest = null;
      oldCtx.close().catch(() => {});
    }
  }
}
