const params = new URLSearchParams(window.location.search);
const room = (params.get("room") || "DEMO").toUpperCase();

const roomChip = document.getElementById("roomChip");
const liveBadgeText = document.getElementById("liveBadgeText");
const callerFrame = document.getElementById("callerFrame");
const seniorFrame = document.getElementById("seniorFrame");
const familyFrame = document.getElementById("familyFrame");
const qrImage = document.getElementById("qrImage");
const qrLink = document.getElementById("qrLink");
const callerCanvas = document.getElementById("callerCanvas");
const assistantCanvas = document.getElementById("assistantCanvas");
const callerCaptionText = document.getElementById("callerCaptionText");
const assistantCaptionText = document.getElementById("assistantCaptionText");
const metricSpeech = document.getElementById("metricSpeech");
const metricTap = document.getElementById("metricTap");
const recordBtn = document.getElementById("recordBtn");
const countdownOverlay = document.getElementById("countdownOverlay");

roomChip.textContent = `Room: ${room}`;
callerFrame.src = `/caller?room=${encodeURIComponent(room)}&embed=1`;
seniorFrame.src = `/senior?room=${encodeURIComponent(room)}&embed=1`;
familyFrame.src = `/family?room=${encodeURIComponent(room)}&embed=1`;

const familyUrl = `${window.location.origin}/family?room=${encodeURIComponent(room)}`;
qrImage.src = `/api/qr?url=${encodeURIComponent(familyUrl)}`;
qrLink.href = familyUrl;
qrLink.textContent = familyUrl;

let callerBins = new Array(16).fill(0.04);
let assistantBins = new Array(16).fill(0.04);
let remoteCallerPulse = 0;
let remoteAssistantPulse = 0;

window.addEventListener("message", (ev) => {
  if (ev.data && ev.data.type === "vouch_audio_levels") {
    callerBins = ev.data.callerBins || callerBins;
    assistantBins = ev.data.assistantBins || assistantBins;
  }
});

function drawBars(canvas, bins, color, pulseBoost) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const count = bins.length;
  const gap = 3;
  const barW = (w - gap * (count + 1)) / count;
  ctx.fillStyle = color;
  for (let i = 0; i < count; i++) {
    const wave = pulseBoost > 0.02 ? pulseBoost * (0.4 + 0.6 * Math.abs(Math.sin(Date.now() / 90 + i))) : 0;
    const val = Math.max(0.08, Math.min(1, (bins[i] || 0) + wave));
    const barH = Math.max(3, val * (h - 8));
    const x = gap + i * (barW + gap);
    const y = (h - barH) / 2;
    ctx.beginPath();
    ctx.roundRect(x, y, barW, barH, 2);
    ctx.fill();
  }
}

function renderLoop() {
  remoteCallerPulse *= 0.92;
  remoteAssistantPulse *= 0.92;
  drawBars(callerCanvas, callerBins, "#38bdf8", remoteCallerPulse);
  drawBars(assistantCanvas, assistantBins, "#22c55e", remoteAssistantPulse);
  requestAnimationFrame(renderLoop);
}
requestAnimationFrame(renderLoop);

function updateMetrics(metrics) {
  if (!metrics) return;
  if (metrics.speech_to_first_audio_s != null) {
    metricSpeech.innerHTML = `Speech &rarr; voice: <strong>${metrics.speech_to_first_audio_s.toFixed(2)}s</strong>`;
  }
  if (metrics.tap_to_first_audio_s != null) {
    metricTap.innerHTML = `Tap &rarr; voice: <strong>${metrics.tap_to_first_audio_s.toFixed(2)}s</strong>`;
  }
}

function connectDemoWs() {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${window.location.host}/ws?room=${encodeURIComponent(room)}&role=demo`);

  ws.onmessage = (ev) => {
    if (typeof ev.data !== "string") return;
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }

    if (msg.type === "room_snapshot") {
      if (msg.mock) {
        liveBadgeText.textContent = "Mock mode · UI preview";
      } else {
        liveBadgeText.textContent = "Gemini Live · real-time audio";
      }
      if (msg.transcripts && msg.transcripts.length > 0) {
        for (const t of msg.transcripts) {
          if (t.speaker === "caller") callerCaptionText.textContent = t.text;
          if (t.speaker === "assistant") assistantCaptionText.textContent = t.text;
        }
      }
      updateMetrics(msg.metrics);
    } else if (msg.type === "call_started") {
      callerCaptionText.textContent = "Connected — listening...";
      assistantCaptionText.textContent = "Screening incoming call...";
      metricSpeech.innerHTML = `Speech &rarr; voice: <strong>&mdash;</strong>`;
      metricTap.innerHTML = `Tap &rarr; voice: <strong>&mdash;</strong>`;
    } else if (msg.type === "transcript") {
      if (msg.speaker === "caller") {
        callerCaptionText.textContent = msg.text;
        remoteCallerPulse = 0.7;
      } else {
        assistantCaptionText.textContent = msg.text;
        remoteAssistantPulse = 0.75;
      }
    } else if (msg.type === "call_ended") {
      updateMetrics(msg.metrics);
    }
  };

  ws.onclose = () => {
    setTimeout(connectDemoWs, 1200);
  };
}
connectDemoWs();

// Section 10b: Record button on /demo (getDisplayMedia + Web Audio mix -> MediaRecorder -> .webm)
let activeRecorder = null;

recordBtn.addEventListener("click", async () => {
  if (activeRecorder && activeRecorder.state === "recording") {
    activeRecorder.stop();
    return;
  }

  let displayStream;
  try {
    displayStream = await navigator.mediaDevices.getDisplayMedia({
      video: { frameRate: 30 },
      audio: true,
    });
  } catch (err) {
    console.warn("Screen share cancelled:", err);
    return;
  }

  // 3-second countdown per SPEC section 10b
  countdownOverlay.classList.remove("hidden");
  for (const n of ["3", "2", "1"]) {
    countdownOverlay.textContent = n;
    await new Promise((r) => setTimeout(r, 1000));
  }
  countdownOverlay.classList.add("hidden");
  recordBtn.classList.add("hidden"); // Hide button while recording per SPEC 10b

  // Mix display audio (if any) + Caller iframe Web Audio mix (caller mic + assistant voice)
  const mixCtx = new (window.AudioContext || window.webkitAudioContext)();
  const mixDest = mixCtx.createMediaStreamDestination();

  if (displayStream.getAudioTracks().length > 0) {
    const dispSrc = mixCtx.createMediaStreamSource(displayStream);
    dispSrc.connect(mixDest);
  }

  try {
    const iframeStream =
      callerFrame.contentWindow &&
      callerFrame.contentWindow.__vouchGetRecordStream &&
      callerFrame.contentWindow.__vouchGetRecordStream();
    if (iframeStream && iframeStream.getAudioTracks().length > 0) {
      const iframeSrc = mixCtx.createMediaStreamSource(iframeStream);
      iframeSrc.connect(mixDest);
    }
  } catch (err) {
    console.warn("Could not attach caller audio mix:", err);
  }

  const combinedTracks = [
    ...displayStream.getVideoTracks(),
    ...mixDest.stream.getAudioTracks(),
  ];
  const combinedStream = new MediaStream(combinedTracks);

  const mime = MediaRecorder.isTypeSupported("video/webm;codecs=vp9,opus")
    ? "video/webm;codecs=vp9,opus"
    : "video/webm";
  const chunks = [];
  const recorder = new MediaRecorder(combinedStream, { mimeType: mime });
  activeRecorder = recorder;

  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) chunks.push(e.data);
  };

  const finishRecording = () => {
    if (recorder.state !== "inactive") {
      recorder.stop();
    }
  };
  displayStream.getVideoTracks()[0].addEventListener("ended", finishRecording);
  window.addEventListener("keydown", function onEsc(e) {
    if (e.key === "Escape") {
      window.removeEventListener("keydown", onEsc);
      finishRecording();
    }
  });

  recorder.onstop = () => {
    recordBtn.classList.remove("hidden");
    for (const t of displayStream.getTracks()) t.stop();
    mixCtx.close().catch(() => {});
    const blob = new Blob(chunks, { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `vouch-demo-${room.toLowerCase()}.webm`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    activeRecorder = null;
  };

  recorder.start(250);
});
