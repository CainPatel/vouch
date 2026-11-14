import { CallerAudioEngine } from "/static/js/audio-engine.js";

const params = new URLSearchParams(window.location.search);
const room = (params.get("room") || "DEMO").toUpperCase();
const isEmbedded = params.get("embed") === "1";
if (isEmbedded) {
  document.getElementById("bodyRoot").classList.add("embedded");
}

const statePill = document.getElementById("statePill");
const stateText = document.getElementById("stateText");
const callBtn = document.getElementById("callBtn");
const callBtnLabel = document.getElementById("callBtnLabel");
const muteBtn = document.getElementById("muteBtn");
const pttToggleBtn = document.getElementById("pttToggleBtn");
const pttHoldBtn = document.getElementById("pttHoldBtn");
const transcriptBox = document.getElementById("transcriptBox");
const transcriptEmpty = document.getElementById("transcriptEmpty");
const textForm = document.getElementById("textForm");
const textInput = document.getElementById("textInput");

const SCENARIOS = {
  grandson: {
    clip: "/static/audio/grandson_bail.wav",
    text: "Grandma, it's Jake. I'm in trouble, I need $4,000 for bail. Please don't tell Mom.",
  },
  bank: {
    clip: "/static/audio/bank_fraud.wav",
    text: "This is the fraud department at your bank. We've detected suspicious activity and need to move your funds to a safe account right now.",
  },
  pharmacy: {
    clip: "/static/audio/pharmacy.wav",
    text: "Hi, this is Dana from Elm Street Pharmacy. Ruth's prescription is ready for pickup.",
  },
};

let ws = null;
let callActive = false;
let isMockMode = false;
let transcripts = [];

const audio = new CallerAudioEngine({
  onPcm16kFrame: (pcmBuffer) => {
    if (ws && ws.readyState === WebSocket.OPEN && callActive) {
      ws.send(pcmBuffer);
    }
  },
  onClipEnded: () => {
    document.querySelectorAll(".scenario-btn").forEach((b) => b.classList.remove("playing"));
  },
});

// Expose recording mix stream for /demo same-origin parent
window.__vouchGetRecordStream = () => (audio.recordDest ? audio.recordDest.stream : null);

function setStateUI(state) {
  statePill.className = `state-pill ${state}`;
  stateText.textContent = state.replace("_", " ");
  const inCall = state === "screening" || state === "verifying";
  callActive = inCall;
  if (inCall) {
    callBtn.className = "call-btn hangup";
    callBtnLabel.textContent = "End Call";
  } else {
    callBtn.className = "call-btn start";
    callBtnLabel.textContent = "Call Ruth";
  }
}

function renderTranscripts() {
  transcriptBox.innerHTML = "";
  if (transcripts.length === 0) {
    transcriptBox.appendChild(transcriptEmpty);
    return;
  }
  for (const t of transcripts) {
    const div = document.createElement("div");
    div.className = `bubble ${t.speaker}`;
    const spk = document.createElement("span");
    spk.className = "spk";
    spk.textContent = t.speaker === "assistant" ? "Ruth's Assistant" : "Caller";
    const body = document.createElement("span");
    body.textContent = t.text;
    div.appendChild(spk);
    div.appendChild(body);
    transcriptBox.appendChild(div);
  }
  transcriptBox.scrollTop = transcriptBox.scrollHeight;
}

function upsertTranscript(speaker, text, final) {
  if (transcripts.length > 0) {
    const last = transcripts[transcripts.length - 1];
    if (last.speaker === speaker && !last.final) {
      last.text = text;
      last.final = final;
      renderTranscripts();
      return;
    }
  }
  transcripts.push({ speaker, text, final });
  renderTranscripts();
}

function connectWs() {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${window.location.host}/ws?room=${encodeURIComponent(room)}&role=caller`);
  ws.binaryType = "arraybuffer";

  ws.onmessage = async (ev) => {
    if (ev.data instanceof ArrayBuffer) {
      // Ensure playback AudioContext is initialized even if call was started elsewhere
      if (!audio.ctx) {
        try {
          await audio.init({ enableMic: false });
        } catch (_) {}
      }
      audio.enqueueAssistantPcm24k(ev.data);
      return;
    }
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }

    if (msg.type === "room_snapshot") {
      isMockMode = Boolean(msg.mock);
      window.__vouchMockMode = isMockMode;
      transcripts = (msg.transcripts || []).map((t) => ({ ...t }));
      renderTranscripts();
      setStateUI(msg.state || "idle");
    } else if (msg.type === "call_started") {
      transcripts = [];
      renderTranscripts();
      audio.resetStats();
      callActive = true;
      setStateUI("screening");
    } else if (msg.type === "status") {
      setStateUI(msg.state);
    } else if (msg.type === "transcript") {
      upsertTranscript(msg.speaker, msg.text, msg.final);
    } else if (msg.type === "verification_answered") {
      audio.markVerificationAnswered();
    } else if (msg.type === "assistant_interrupted") {
      audio.flushAssistantPlayback();
    } else if (msg.type === "call_ended") {
      callActive = false;
      audio.stopMic();
      document.querySelectorAll(".scenario-btn").forEach((b) => b.classList.remove("playing"));
      setStateUI("idle");
    }
  };

  ws.onclose = () => {
    setTimeout(connectWs, 1200);
  };
}

async function waitWsOpen(timeoutMs = 4000) {
  const start = Date.now();
  while ((!ws || ws.readyState !== WebSocket.OPEN) && Date.now() - start < timeoutMs) {
    await new Promise((r) => setTimeout(r, 40));
  }
}

async function startLiveCall({ withMic = true } = {}) {
  await waitWsOpen();
  await audio.init({ enableMic: withMic });
  audio.flushAssistantPlayback();
  audio.resetStats();
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "start_call" }));
    callActive = true;
    setStateUI("screening");
  }
}

callBtn.addEventListener("click", async () => {
  if (callActive) {
    audio.stopMic({ flushPlayback: true });
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "end_call" }));
    }
    callActive = false;
    setStateUI("idle");
  } else {
    await startLiveCall({ withMic: true });
  }
});

muteBtn.addEventListener("click", () => {
  const next = !audio.muted;
  audio.setMuted(next);
  muteBtn.textContent = next ? "Muted" : "Mic Open";
  muteBtn.classList.toggle("active", next);
});

pttToggleBtn.addEventListener("click", () => {
  const next = !audio.pushToTalk;
  audio.setPushToTalk(next);
  pttToggleBtn.textContent = next ? "Push-to-Talk: On" : "Push-to-Talk: Off";
  pttToggleBtn.classList.toggle("active", next);
  pttHoldBtn.classList.toggle("hidden", !next);
});

for (const evName of ["mousedown", "touchstart"]) {
  pttHoldBtn.addEventListener(evName, (e) => {
    e.preventDefault();
    audio.setPttHeld(true);
    pttHoldBtn.classList.add("active");
  });
}
for (const evName of ["mouseup", "mouseleave", "touchend"]) {
  pttHoldBtn.addEventListener(evName, () => {
    if (audio.pttHeld) {
      audio.setPttHeld(false);
      pttHoldBtn.classList.remove("active");
      if (ws && ws.readyState === WebSocket.OPEN && callActive) {
        ws.send(JSON.stringify({ type: "caller_speech_end" }));
      }
    }
  });
}

document.querySelectorAll(".scenario-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const key = btn.dataset.scenario;
    const spec = SCENARIOS[key];
    if (!spec) return;

    document.querySelectorAll(".scenario-btn").forEach((b) => b.classList.remove("playing"));
    btn.classList.add("playing");

    if (isMockMode) {
      if (!callActive) {
        await startLiveCall({ withMic: false });
        await new Promise((r) => setTimeout(r, 150));
      }
      ws.send(JSON.stringify({ type: "caller_text", text: spec.text }));
      btn.classList.remove("playing");
      return;
    }

    if (!callActive) {
      // Mute live mic during scripted clip playback so ambient noise doesn't collide, while worklet captures clip
      await startLiveCall({ withMic: false });
      await new Promise((r) => setTimeout(r, 450));
    }
    try {
      await audio.playScriptedClip(spec.clip);
    } catch (err) {
      console.warn("Clip playback fell back to text:", err);
      ws.send(JSON.stringify({ type: "caller_text", text: spec.text }));
      btn.classList.remove("playing");
    }
  });
});

textForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const val = textInput.value.trim();
  if (!val) return;
  textInput.value = "";
  if (!audio.ctx) {
    try {
      await audio.init({ enableMic: false });
    } catch (_) {}
  }
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "caller_text", text: val }));
  }
});

// Stream live frequency bins to /demo parent frame at ~25fps
if (window.parent && window.parent !== window) {
  setInterval(() => {
    if (!audio.ctx) return;
    const levels = audio.getLevels();
    window.parent.postMessage({ type: "vouch_audio_levels", ...levels }, "*");
  }, 40);
}

connectWs();
