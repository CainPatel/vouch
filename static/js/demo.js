const params = new URLSearchParams(window.location.search);
const room = (params.get("room") || "DEMO").toUpperCase();

const roomChip = document.getElementById("roomChip");
const newRoomBtn = document.getElementById("newRoomBtn");
const liveBadgeText = document.getElementById("liveBadgeText");
const callerFrame = document.getElementById("callerFrame");
const seniorFrame = document.getElementById("seniorFrame");
const familyFrame = document.getElementById("familyFrame");
const qrImage = document.getElementById("qrImage");
const qrLink = document.getElementById("qrLink");
const copyQrBtn = document.getElementById("copyQrBtn");
const callerCanvas = document.getElementById("callerCanvas");
const assistantCanvas = document.getElementById("assistantCanvas");
const callerCaptionText = document.getElementById("callerCaptionText");
const assistantCaptionText = document.getElementById("assistantCaptionText");
const metricSpeech = document.getElementById("metricSpeech");
const metricTap = document.getElementById("metricTap");
const recordBtn = document.getElementById("recordBtn");
const countdownOverlay = document.getElementById("countdownOverlay");

roomChip.textContent = `Room · ${room}`;
callerFrame.src = `/caller?room=${encodeURIComponent(room)}&embed=1&v=5`;
seniorFrame.src = `/senior?room=${encodeURIComponent(room)}&embed=1&v=5`;
familyFrame.src = `/family?room=${encodeURIComponent(room)}&embed=1&v=5`;

let activeFamilyUrl = `${window.location.origin}/family?room=${encodeURIComponent(room)}`;

function applyQrUrl(url) {
  activeFamilyUrl = url;
  qrImage.src = `/api/qr?url=${encodeURIComponent(url)}`;
  qrLink.href = url;
  try {
    const parsed = new URL(url);
    qrLink.textContent = `${parsed.host}/family?room=${room}`;
  } catch {
    qrLink.textContent = url;
  }
}

applyQrUrl(activeFamilyUrl);

// When opened on localhost, automatically resolve public HTTPS tunnel if present so phone QR scan works over Wi-Fi/5G
if (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") {
  fetch(`/static/tunnel.json?t=${Date.now()}`, { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      if (data && data.public_origin && data.public_origin.startsWith("https://")) {
        const cleanOrigin = data.public_origin.replace(/\/+$/, "");
        applyQrUrl(`${cleanOrigin}/family?room=${encodeURIComponent(room)}`);
      }
    })
    .catch(() => {});
}

if (copyQrBtn) {
  copyQrBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(activeFamilyUrl);
      const orig = copyQrBtn.textContent;
      copyQrBtn.textContent = "Copied Link ✓";
      setTimeout(() => {
        copyQrBtn.textContent = orig;
      }, 1600);
    } catch {
      window.open(activeFamilyUrl, "_blank", "noopener");
    }
  });
}

if (newRoomBtn) {
  newRoomBtn.addEventListener("click", () => {
    window.location.href = "/demo";
  });
}

let callerBins = new Array(20).fill(0.05);
let assistantBins = new Array(20).fill(0.05);
let remoteCallerPulse = 0;
let remoteAssistantPulse = 0;

window.addEventListener("message", (ev) => {
  if (ev.data && ev.data.type === "vouch_audio_levels") {
    callerBins = ev.data.callerBins || callerBins;
    assistantBins = ev.data.assistantBins || assistantBins;
  }
});

function drawBars(canvas, bins, colorTop, colorBottom, pulseBoost) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const count = bins.length;
  const gap = 3;
  const barW = Math.max(2, (w - gap * (count + 1)) / count);
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, colorTop);
  grad.addColorStop(1, colorBottom);
  ctx.fillStyle = grad;

  for (let i = 0; i < count; i++) {
    const wave =
      pulseBoost > 0.02
        ? pulseBoost * (0.35 + 0.65 * Math.abs(Math.sin(Date.now() / 85 + i * 0.7)))
        : 0;
    const val = Math.max(0.08, Math.min(1, (bins[i] || 0) + wave));
    const barH = Math.max(3, val * (h - 6));
    const x = gap + i * (barW + gap);
    const y = (h - barH) / 2;
    ctx.beginPath();
    ctx.roundRect(x, y, barW, barH, 99);
    ctx.fill();
  }
}

function renderLoop() {
  remoteCallerPulse *= 0.92;
  remoteAssistantPulse *= 0.92;
  drawBars(callerCanvas, callerBins, "#7dd3fc", "#0ea5e9", remoteCallerPulse);
  drawBars(assistantCanvas, assistantBins, "#6ee7b7", "#10b981", remoteAssistantPulse);
  requestAnimationFrame(renderLoop);
}
requestAnimationFrame(renderLoop);

function updateMetrics(metrics) {
  if (!metrics) return;
  if (metrics.speech_to_first_audio_s != null) {
    metricSpeech.innerHTML = `<span>Speech &rarr; voice</span><strong>${metrics.speech_to_first_audio_s.toFixed(2)}s</strong>`;
  }
  if (metrics.tap_to_first_audio_s != null) {
    metricTap.innerHTML = `<span>Tap &rarr; voice</span><strong>${metrics.tap_to_first_audio_s.toFixed(2)}s</strong>`;
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
        liveBadgeText.textContent = "Gemini Live · Real-Time Audio";
      }
      if (msg.transcripts && msg.transcripts.length > 0) {
        for (const t of msg.transcripts) {
          if (t.speaker === "caller") callerCaptionText.textContent = t.text;
          if (t.speaker === "assistant") assistantCaptionText.textContent = t.text;
        }
      }
      updateMetrics(msg.metrics);
    } else if (msg.type === "call_started") {
      callerCaptionText.textContent = "Connected — listening to caller...";
      assistantCaptionText.textContent = "Screening incoming call silently...";
      metricSpeech.innerHTML = `<span>Speech &rarr; voice</span><strong>&mdash;</strong>`;
      metricTap.innerHTML = `<span>Tap &rarr; voice</span><strong>&mdash;</strong>`;
    } else if (msg.type === "transcript") {
      if (msg.speaker === "caller") {
        callerCaptionText.textContent = msg.text;
        remoteCallerPulse = 0.72;
      } else {
        assistantCaptionText.textContent = msg.text;
        remoteAssistantPulse = 0.78;
      }
    } else if (msg.type === "metrics") {
      updateMetrics(msg.metrics);
    } else if (msg.type === "call_ended") {
      updateMetrics(msg.metrics);
    }
  };

  ws.onclose = () => {
    setTimeout(connectDemoWs, 1200);
  };
}
connectDemoWs();

// Record button on /demo (getDisplayMedia + Web Audio mix -> MediaRecorder -> .webm)
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
    console.warn("Screen share failed/cancelled:", err);
    const msg =
      err && err.name === "NotAllowedError"
        ? "Screen recording was cancelled or blocked. Select the 'Chrome Tab' ('Vouch · Live Demo View') and click Share — or enable Chrome under macOS System Settings -> Privacy & Security -> Screen & System Audio Recording."
        : `Could not start screen capture: ${err}`;
    alert(msg);
    return;
  }

  let iframeAudioTracks = [];
  try {
    const iframeStream =
      callerFrame.contentWindow &&
      callerFrame.contentWindow.__vouchGetRecordStream &&
      (await callerFrame.contentWindow.__vouchGetRecordStream());
    if (iframeStream && iframeStream.getAudioTracks().length > 0) {
      iframeAudioTracks = iframeStream.getAudioTracks();
    }
  } catch (err) {
    console.warn("Could not attach caller audio mix:", err);
  }

  countdownOverlay.classList.remove("hidden");
  for (const n of ["3", "2", "1"]) {
    countdownOverlay.textContent = n;
    await new Promise((r) => setTimeout(r, 1000));
  }
  countdownOverlay.classList.add("hidden");
  recordBtn.classList.add("hidden");
  roomChip.textContent = `● REC · ${room} (Esc or click to stop)`;
  roomChip.style.borderColor = "rgba(244, 63, 94, 0.75)";
  roomChip.style.color = "#fda4af";
  roomChip.style.cursor = "pointer";

  const audioTracks =
    iframeAudioTracks.length > 0 ? iframeAudioTracks : displayStream.getAudioTracks();

  const combinedStream = new MediaStream([
    ...displayStream.getVideoTracks(),
    ...audioTracks,
  ]);

  let recorder;
  let mime = "video/webm";
  for (const candidate of [
    "video/webm;codecs=vp9,opus",
    "video/webm;codecs=vp8,opus",
    "video/webm",
  ]) {
    if (MediaRecorder.isTypeSupported(candidate)) {
      mime = candidate;
      break;
    }
  }
  try {
    recorder = new MediaRecorder(combinedStream, { mimeType: mime });
  } catch (_) {
    recorder = new MediaRecorder(combinedStream);
  }
  const chunks = [];
  activeRecorder = recorder;

  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) chunks.push(e.data);
  };

  const escTargets = [
    window,
    callerFrame.contentWindow,
    seniorFrame.contentWindow,
    familyFrame.contentWindow,
  ].filter(Boolean);

  function onEsc(e) {
    if (e.key === "Escape") {
      finishRecording();
    }
  }

  const finishRecording = () => {
    roomChip.onclick = null;
    roomChip.textContent = `Room · ${room}`;
    roomChip.style.borderColor = "";
    roomChip.style.color = "";
    roomChip.style.cursor = "";
    for (const w of escTargets) {
      try {
        w.removeEventListener("keydown", onEsc);
      } catch (_) {}
    }
    if (recorder.state !== "inactive") {
      recorder.stop();
    }
  };
  roomChip.onclick = finishRecording;
  displayStream.getVideoTracks()[0].addEventListener("ended", finishRecording);
  for (const w of escTargets) {
    try {
      w.addEventListener("keydown", onEsc);
    } catch (_) {}
  }

  recorder.onstop = () => {
    try {
      if (callerFrame.contentWindow && callerFrame.contentWindow.__vouchSetRecordingActive) {
        callerFrame.contentWindow.__vouchSetRecordingActive(false);
      }
    } catch (_) {}
    recordBtn.classList.remove("hidden");
    for (const t of displayStream.getTracks()) t.stop();
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
