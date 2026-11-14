const params = new URLSearchParams(window.location.search);
const room = (params.get("room") || "DEMO").toUpperCase();
if (params.get("embed") === "1") {
  document.getElementById("bodyRoot").classList.add("embedded");
}

const statePill = document.getElementById("statePill");
const stateText = document.getElementById("stateText");
const statusCard = document.getElementById("statusCard");
const statusKicker = document.getElementById("statusKicker");
const statusHeadline = document.getElementById("statusHeadline");
const statusSub = document.getElementById("statusSub");
const carbonCard = document.getElementById("carbonCard");
const carbonLabel = document.getElementById("carbonLabel");
const carbonClaim = document.getElementById("carbonClaim");
const carbonPattern = document.getElementById("carbonPattern");
const carbonAction = document.getElementById("carbonAction");
const carbonNext = document.getElementById("carbonNext");
const transcriptBox = document.getElementById("transcriptBox");
const transcriptEmpty = document.getElementById("transcriptEmpty");
const historyList = document.getElementById("historyList");

let transcripts = [];
let historyItems = [];
let stickyVerdict = null; // Keep verdict prominently visible after call returns to idle

function updatePill(state) {
  statePill.className = `state-pill ${state}`;
  stateText.textContent = state.replace("_", " ");
}

function showStatusCard(variant, kicker, headline, sub) {
  statusCard.className = `hero-status-card ${variant}`;
  statusKicker.textContent = kicker;
  statusHeadline.textContent = headline;
  statusSub.textContent = sub;
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
    spk.textContent = t.speaker === "assistant" ? "Vouch Assistant" : "Unknown Caller";
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

function renderHistory() {
  historyList.innerHTML = "";
  if (!historyItems || historyItems.length === 0) {
    const empty = document.createElement("div");
    empty.className = "transcript-empty";
    empty.textContent = "No screened calls yet.";
    historyList.appendChild(empty);
    return;
  }
  for (const h of historyItems) {
    const row = document.createElement("div");
    row.className = "history-item";
    const textSpan = document.createElement("span");
    textSpan.textContent = h.headline;
    const badge = document.createElement("span");
    badge.className = `history-badge ${h.outcome}`;
    badge.textContent = h.outcome.replace("_", " ");
    row.appendChild(textSpan);
    row.appendChild(badge);
    historyList.appendChild(row);
  }
}

function renderReport(rep) {
  if (!rep || !rep.structured) {
    carbonCard.classList.add("hidden");
    return;
  }
  carbonLabel.textContent = rep.model_label || "Report by Gemini 4 Carbon";
  carbonClaim.innerHTML = `<strong>Claim:</strong> ${escapeHtml(rep.structured.claim || "")}`;
  carbonPattern.innerHTML = `<strong>Pattern:</strong> ${escapeHtml(rep.structured.pattern || "")}`;
  carbonAction.innerHTML = `<strong>Vouch did:</strong> ${escapeHtml(rep.structured.action_taken || "")}`;
  carbonNext.innerHTML = `<strong>Next step:</strong> ${escapeHtml(rep.structured.next_step || "")}`;
  carbonCard.classList.remove("hidden");
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function applyVerdictCard(verdict) {
  if (!verdict) return;
  stickyVerdict = verdict;
  if (verdict.outcome === "blocked") {
    showStatusCard(
      "blocked",
      "Scam Call Blocked · Phone Never Rang",
      verdict.headline,
      "Ruth was never interrupted. Family has been notified."
    );
  } else if (verdict.outcome === "passed") {
    showStatusCard(
      "passed",
      "Ringing Ruth Now · Verified Caller",
      `Incoming call: ${verdict.summary || verdict.headline}`,
      "Vouch verified ordinary business and is ringing Ruth's phone."
    );
  } else if (verdict.outcome === "message_taken") {
    showStatusCard(
      "message_taken",
      "Held · Message Taken",
      verdict.headline,
      "Caller could not be confirmed immediately; phone did not ring."
    );
  }
}

function connectWs() {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${window.location.host}/ws?room=${encodeURIComponent(room)}&role=senior`);

  ws.onmessage = (ev) => {
    if (typeof ev.data !== "string") return;
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }

    if (msg.type === "room_snapshot") {
      transcripts = (msg.transcripts || []).map((t) => ({ ...t }));
      historyItems = msg.history || [];
      renderTranscripts();
      renderHistory();
      updatePill(msg.state || "idle");
      if (msg.last_verdict) {
        applyVerdictCard(msg.last_verdict);
      } else if (msg.state === "screening") {
        showStatusCard(
          "screening",
          "Silent Screening Active",
          "Vouch is screening an unknown caller",
          "Ruth's phone stays silent while Vouch checks who is calling."
        );
      } else if (msg.state === "verifying" && msg.verification) {
        showStatusCard(
          "verifying",
          "Out-of-Band Family Check",
          `Checking with ${msg.verification.claimed_name}...`,
          `Caller claimed to be ${msg.verification.claimed_name} (${msg.verification.ask || "urgent request"}).`
        );
      }
      if (msg.last_report) {
        renderReport(msg.last_report);
      }
    } else if (msg.type === "call_started") {
      stickyVerdict = null;
      carbonCard.classList.add("hidden");
      transcripts = [];
      renderTranscripts();
      updatePill("screening");
      showStatusCard(
        "screening",
        "Silent Screening Active",
        "Vouch is screening an unknown caller",
        "Ruth's phone stays silent while Vouch checks who is calling."
      );
    } else if (msg.type === "status") {
      // Keep blocked/passed badge visible on pill if stickyVerdict is set and state returned to idle
      if (msg.state === "idle" && stickyVerdict) {
        updatePill(stickyVerdict.outcome);
      } else {
        updatePill(msg.state);
      }
    } else if (msg.type === "verification_requested") {
      updatePill("verifying");
      const amtPart = msg.amount ? ` asking for ${msg.amount}` : "";
      showStatusCard(
        "verifying",
        "Verifying Family Claim",
        `Pinging ${msg.claimed_name}'s phone right now...`,
        `Caller claims to be ${msg.claimed_name}${amtPart}. Holding caller.`
      );
    } else if (msg.type === "verification_answered") {
      if (msg.answer === "denied") {
        showStatusCard(
          "blocked",
          "Impersonation Confirmed",
          "Real family member tapped 'Not me' — disconnecting caller...",
          "Ruth's phone never rang."
        );
      }
    } else if (msg.type === "call_blocked") {
      applyVerdictCard({
        outcome: "blocked",
        headline: msg.headline,
        reason: msg.reason,
      });
      updatePill("blocked");
    } else if (msg.type === "call_passed_through") {
      applyVerdictCard({
        outcome: "passed",
        summary: msg.summary,
        headline: msg.summary,
      });
      updatePill("passed");
    } else if (msg.type === "call_message_taken") {
      applyVerdictCard({
        outcome: "message_taken",
        summary: msg.summary,
        headline: `Message taken: ${msg.summary}`,
      });
      updatePill("message_taken");
    } else if (msg.type === "transcript") {
      upsertTranscript(msg.speaker, msg.text, msg.final);
    } else if (msg.type === "call_ended") {
      if (msg.history_item) {
        historyItems.unshift(msg.history_item);
        historyItems = historyItems.slice(0, 10);
        renderHistory();
      }
      if (!stickyVerdict) {
        updatePill("idle");
        showStatusCard(
          "",
          "Protected · Silent Mode",
          "Unknown calls are answered by Vouch before Ruth's phone rings.",
          "Known contacts ring straight through. Unknown callers are screened silently."
        );
      }
    } else if (msg.type === "family_report") {
      renderReport(msg);
    }
  };

  ws.onclose = () => {
    setTimeout(connectWs, 1200);
  };
}

connectWs();
