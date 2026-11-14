const params = new URLSearchParams(window.location.search);
const room = (params.get("room") || "DEMO").toUpperCase();
if (params.get("embed") === "1") {
  document.getElementById("bodyRoot").classList.add("embedded");
}

const familyOwnerTitle = document.getElementById("familyOwnerTitle");
const statePill = document.getElementById("statePill");
const stateText = document.getElementById("stateText");
const idleCard = document.getElementById("idleCard");
const verifyCard = document.getElementById("verifyCard");
const verifyQuestion = document.getElementById("verifyQuestion");
const valName = document.getElementById("valName");
const valRel = document.getElementById("valRel");
const valAsk = document.getElementById("valAsk");
const valAmount = document.getElementById("valAmount");
const verifyActions = document.getElementById("verifyActions");
const btnNotMe = document.getElementById("btnNotMe");
const btnYesMe = document.getElementById("btnYesMe");
const resolvedBanner = document.getElementById("resolvedBanner");
const carbonCard = document.getElementById("carbonCard");
const carbonLabel = document.getElementById("carbonLabel");
const carbonClaim = document.getElementById("carbonClaim");
const carbonPattern = document.getElementById("carbonPattern");
const carbonAction = document.getElementById("carbonAction");
const carbonNext = document.getElementById("carbonNext");

let ws = null;
let currentVerificationId = null;
let lastNonVerifyBlocked = false;

function setPill(cls, label) {
  statePill.className = `state-pill ${cls}`;
  stateText.textContent = label;
}

function showVerification(ver) {
  currentVerificationId = ver.id;
  const name = ver.claimed_name || "Family member";
  familyOwnerTitle.textContent = `${name}'s Phone`;
  const askPhrase = ver.amount
    ? `asking for ${ver.amount}${ver.ask ? ` (${ver.ask})` : ""}`
    : ver.ask
    ? `about ${ver.ask}`
    : "asking to speak urgently";
  verifyQuestion.textContent = `Someone claiming to be you is on the phone with Ruth ${askPhrase}. Is this you?`;
  valName.textContent = name;
  valRel.textContent = ver.relationship || "family";
  valAsk.textContent = ver.ask || "urgent request";
  valAmount.textContent = ver.amount || "Not stated";

  idleCard.classList.add("hidden");
  verifyCard.classList.remove("hidden");

  if (ver.answer) {
    showAnswered(ver.answer);
  } else {
    setPill("verifying", "action needed");
    verifyActions.classList.remove("hidden");
    resolvedBanner.classList.add("hidden");
  }
}

function showAnswered(answer) {
  verifyActions.classList.add("hidden");
  resolvedBanner.classList.remove("hidden");
  if (answer === "denied") {
    setPill("blocked", "not me");
    resolvedBanner.className = "verify-resolved-banner denied";
    resolvedBanner.textContent = "Denied ('Not me') — Vouch disconnected the scammer.";
  } else if (answer === "confirmed") {
    setPill("passed", "confirmed");
    resolvedBanner.className = "verify-resolved-banner confirmed";
    resolvedBanner.textContent = "Confirmed — Vouch is connecting your call to Ruth.";
  } else {
    setPill("message_taken", "timed out");
    resolvedBanner.className = "verify-resolved-banner denied";
    resolvedBanner.textContent = "Verification timed out — Vouch took a message instead.";
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
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

function sendAnswer(answer) {
  if (!ws || ws.readyState !== WebSocket.OPEN || !currentVerificationId) return;
  ws.send(
    JSON.stringify({
      type: "verification_response",
      id: currentVerificationId,
      answer,
    })
  );
  showAnswered(answer);
}

btnNotMe.addEventListener("click", () => sendAnswer("denied"));
btnYesMe.addEventListener("click", () => sendAnswer("confirmed"));

function connectWs() {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${window.location.host}/ws?room=${encodeURIComponent(room)}&role=family`);

  ws.onmessage = (ev) => {
    if (typeof ev.data !== "string") return;
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }

    if (msg.type === "room_snapshot") {
      if (msg.verification) {
        showVerification(msg.verification);
      } else {
        setPill("", "standby");
        idleCard.classList.remove("hidden");
        verifyCard.classList.add("hidden");
      }
      if (msg.last_report) {
        renderReport(msg.last_report);
        if (!msg.verification && msg.last_report.outcome === "blocked") {
          lastNonVerifyBlocked = true;
          setPill("blocked", "scam blocked");
          idleCard.classList.add("hidden");
        }
      }
    } else if (msg.type === "call_started") {
      currentVerificationId = null;
      lastNonVerifyBlocked = false;
      carbonCard.classList.add("hidden");
      verifyCard.classList.add("hidden");
      idleCard.classList.remove("hidden");
      setPill("screening", "call active");
    } else if (msg.type === "verification_requested") {
      lastNonVerifyBlocked = false;
      showVerification(msg);
      if (navigator.vibrate) {
        try {
          navigator.vibrate([180, 80, 180]);
        } catch (_) {}
      }
    } else if (msg.type === "verification_answered") {
      showAnswered(msg.answer);
    } else if (msg.type === "call_blocked") {
      if (!currentVerificationId) {
        lastNonVerifyBlocked = true;
        setPill("blocked", "scam blocked");
      }
    } else if (msg.type === "call_passed_through") {
      lastNonVerifyBlocked = false;
      if (!currentVerificationId) {
        setPill("", "standby");
      }
    } else if (msg.type === "call_ended") {
      if (!currentVerificationId && !lastNonVerifyBlocked) {
        setPill("", "standby");
      }
    } else if (msg.type === "family_report") {
      renderReport(msg);
      if (!currentVerificationId && lastNonVerifyBlocked) {
        idleCard.classList.add("hidden");
      }
    }
  };

  ws.onclose = () => {
    setTimeout(connectWs, 1200);
  };
}

connectWs();
