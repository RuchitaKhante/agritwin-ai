// ---- Config ----
const API_BASE_URL = "http://localhost:8000";
const SESSION_ID = "session_" + Math.random().toString(36).slice(2, 10);

// ---- Element references ----
const chatWindow = document.getElementById("chatWindow");
const chatForm = document.getElementById("chatForm");
const textInput = document.getElementById("textInput");
const sendButton = document.getElementById("sendButton");
const micButton = document.getElementById("micButton");
const errorBanner = document.getElementById("errorBanner");
const suggestionButtons = document.querySelectorAll(".suggestion-btn");

// ---- Rendering helpers ----

function addUserMessage(text) {
  const div = document.createElement("div");
  div.className = "message user-message";
  div.textContent = text;
  chatWindow.appendChild(div);
  scrollToBottom();
}

function addBotMessage(answer, sources) {
  const wrapper = document.createElement("div");
  wrapper.className = "message bot-message";

  const answerP = document.createElement("p");
  answerP.textContent = answer;
  wrapper.appendChild(answerP);

  const listenBtn = document.createElement("button");
  listenBtn.className = "listen-button";
  listenBtn.textContent = "🔊 Listen";
  listenBtn.addEventListener("click", () => speakText(answer));
  wrapper.appendChild(listenBtn);

  if (sources && sources.length > 0) {
    const sourcesDiv = document.createElement("div");
    sourcesDiv.className = "sources";
    sourcesDiv.textContent = "📚 Sources: " + sources.join(", ");
    wrapper.appendChild(sourcesDiv);
  }

  chatWindow.appendChild(wrapper);
  scrollToBottom();
}

function speakText(text) {
  if (!window.speechSynthesis) {
    showError("Sorry, this browser doesn't support reading answers aloud.");
    return;
  }
  window.speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = detectSpeechLang(text);
  window.speechSynthesis.speak(utterance);
}

function detectSpeechLang(text) {
  const hasDevanagari = /[\u0900-\u097F]/.test(text);
  return hasDevanagari ? "hi-IN" : "en-US";
}

function showLoadingIndicator() {
  const div = document.createElement("div");
  div.className = "loading-indicator";
  div.id = "loadingIndicator";
  div.textContent = "AgriTwin AI is thinking...";
  chatWindow.appendChild(div);
  scrollToBottom();
}

function removeLoadingIndicator() {
  const el = document.getElementById("loadingIndicator");
  if (el) el.remove();
}

function showError(message) {
  errorBanner.textContent = message;
  errorBanner.classList.remove("hidden");
}

function hideError() {
  errorBanner.classList.add("hidden");
}

function scrollToBottom() {
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

// ---- Core: send a question to the backend ----
// Note: sensor data is no longer sent from the frontend manually.
// The backend automatically uses whatever /analyze last recorded
// (see chatbot/latest_reading_store.py).

async function sendQuestion(question) {
  if (!question || !question.trim()) return;

  hideError();
  addUserMessage(question);
  textInput.value = "";
  sendButton.disabled = true;
  showLoadingIndicator();

  try {
    const response = await fetch(`${API_BASE_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: question,
        session_id: SESSION_ID,
      }),
    });

    if (!response.ok) {
      throw new Error(`Server responded with status ${response.status}`);
    }

    const data = await response.json();
    removeLoadingIndicator();
    addBotMessage(data.answer, data.sources);

  } catch (err) {
    console.error("Chat request failed:", err);
    removeLoadingIndicator();
    showError("Sorry, something went wrong reaching AgriTwin AI. Please check your connection and try again.");
  } finally {
    sendButton.disabled = false;
  }
}

// ---- Event listeners ----

chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  sendQuestion(textInput.value);
});

suggestionButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    sendQuestion(btn.textContent);
  });
});

// ---- Voice input (Web Speech API) ----

function setupVoiceInput(micButtonId, textInputId) {
  const micBtn = document.getElementById(micButtonId);
  const input = document.getElementById(textInputId);

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  if (!SpeechRecognition) {
    micBtn.disabled = true;
    micBtn.title = "Voice input not supported in this browser";
    return;
  }

  const recognition = new SpeechRecognition();
  recognition.lang = "en-US";
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  let isListening = false;

  micBtn.addEventListener("click", () => {
    if (isListening) return;
    isListening = true;
    micBtn.classList.add("listening");
    recognition.start();
  });

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    input.value = transcript;
  };

  recognition.onerror = (event) => {
    console.error("Speech recognition error:", event.error);
    showError("Sorry, I couldn't hear that clearly. Please try again or type your question.");
  };

  recognition.onend = () => {
    isListening = false;
    micBtn.classList.remove("listening");
  };
}

setupVoiceInput("micButton", "textInput");