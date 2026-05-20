// Voice Input — Azure GPT-4o transcribe with Web Speech API fallback

let _voiceActive = false;
let _recognition = null;
let _mediaRecorder = null;
let _audioChunks = [];
let _useAzure = false;

async function checkAzureAvailability() {
  try {
    const res = await fetch("/api/voice/status");
    const data = await res.json();
    _useAzure = data.available === true;
  } catch (e) {
    _useAzure = false;
  }
}

function toggleVoice() {
  if (_voiceActive) {
    stopVoice();
  } else {
    startVoice();
  }
}

async function startVoice() {
  const comments = document.getElementById("comments");
  if (comments.value.length > 0 && !comments.value.endsWith("\n")) {
    comments.value = comments.value.trimEnd() + ".\n";
  }

  document.getElementById("btn-voice").classList.remove("btn-outline-secondary");
  document.getElementById("btn-voice").classList.add("btn-danger");
  document.getElementById("voice-status").classList.remove("d-none");
  _voiceActive = true;

  if (_useAzure) {
    startAzureRecording();
  } else {
    startWebSpeech();
  }
}

function stopVoice() {
  _voiceActive = false;
  if (_useAzure) {
    stopAzureRecording();
  } else {
    stopWebSpeech();
  }
  document.getElementById("btn-voice").classList.remove("btn-danger");
  document.getElementById("btn-voice").classList.add("btn-outline-secondary");
  document.getElementById("voice-status").classList.add("d-none");
}

// --- Azure GPT-4o transcription ---
async function startAzureRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    _audioChunks = [];
    _mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
    _mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) _audioChunks.push(e.data);
    };
    _mediaRecorder.start();
    document.getElementById("voice-status").textContent = "Recording (Azure GPT-4o)...";
  } catch (e) {
    showStatus("Microphone access denied: " + e.message, "danger");
    stopVoice();
  }
}

async function stopAzureRecording() {
  if (!_mediaRecorder || _mediaRecorder.state === "inactive") return;

  const stopped = new Promise(resolve => {
    _mediaRecorder.onstop = resolve;
  });
  _mediaRecorder.stop();
  await stopped;

  _mediaRecorder.stream.getTracks().forEach(t => t.stop());

  const audioBlob = new Blob(_audioChunks, { type: "audio/webm" });
  _audioChunks = [];

  if (audioBlob.size < 1000) return;

  document.getElementById("voice-status").textContent = "Transcribing...";
  document.getElementById("voice-status").classList.remove("d-none");

  try {
    const formData = new FormData();
    formData.append("audio", audioBlob, "recording.webm");
    const res = await fetch("/api/voice/transcribe", { method: "POST", body: formData });
    const data = await res.json();
    if (res.ok && data.text) {
      const comments = document.getElementById("comments");
      comments.value = comments.value + data.text;
      if (data.translation) {
        comments.value = comments.value + " (" + data.translation + ")";
      }
    } else {
      showStatus(data.error || "Transcription failed", "warning");
    }
  } catch (e) {
    showStatus("Transcription error: " + e.message, "danger");
  } finally {
    document.getElementById("voice-status").classList.add("d-none");
  }
}

// --- Web Speech API fallback ---
function startWebSpeech() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    showStatus("Speech recognition not supported in this browser. Use Chrome or Edge.", "warning");
    stopVoice();
    return;
  }

  _recognition = new SpeechRecognition();
  _recognition.continuous = true;
  _recognition.interimResults = true;
  _recognition.lang = "en-US";

  const comments = document.getElementById("comments");

  _recognition.onresult = function (event) {
    let final = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) {
        final += event.results[i][0].transcript;
      }
    }
    if (final) {
      comments.value = comments.value + final;
    }
  };

  _recognition.onerror = function (event) {
    if (event.error !== "no-speech") {
      showStatus("Voice error: " + event.error, "warning");
    }
    stopVoice();
  };

  _recognition.onend = function () {
    if (_voiceActive) {
      _recognition.start();
    }
  };

  _recognition.start();
  document.getElementById("voice-status").textContent = "Listening (Web Speech)...";
}

function stopWebSpeech() {
  if (_recognition) {
    _recognition.stop();
    _recognition = null;
  }
}

// -------------------------------------------------------------------------
// Keyword extraction and management
// -------------------------------------------------------------------------
let _keywords = [];

async function extractKeywords() {
  const comments = document.getElementById("comments").value.trim();
  if (!comments) {
    showStatus("Enter some comments first.", "warning");
    return;
  }

  const instrument = document.getElementById("instrument").value;
  document.getElementById("spinner-extract-kw").classList.remove("d-none");

  try {
    const res = await fetch("/api/keywords/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ comments, instrument_name: instrument }),
    });
    const data = await res.json();
    if (res.ok && data.keywords) {
      data.keywords.forEach(kw => {
        if (!_keywords.includes(kw)) _keywords.push(kw);
      });
      renderKeywords();
    } else {
      showStatus(data.error || "Keyword extraction failed", "warning");
    }
  } catch (e) {
    showStatus("Keyword extraction error: " + e.message, "danger");
  } finally {
    document.getElementById("spinner-extract-kw").classList.add("d-none");
  }
}

function addKeywordFromInput() {
  const input = document.getElementById("kw-input");
  const kw = input.value.trim();
  if (kw && !_keywords.includes(kw)) {
    _keywords.push(kw);
    renderKeywords();
  }
  input.value = "";
}

function removeKeyword(index) {
  _keywords.splice(index, 1);
  renderKeywords();
}

function renderKeywords() {
  const container = document.getElementById("keywords-container");
  container.innerHTML = _keywords.map((kw, i) =>
    `<span class="badge bg-primary d-flex align-items-center gap-1">
      ${kw}
      <button type="button" class="btn-close btn-close-white" style="font-size:0.6rem;"
              onclick="removeKeyword(${i})"></button>
    </span>`
  ).join("");
}

function getKeywords() {
  return _keywords;
}

checkAzureAvailability();
