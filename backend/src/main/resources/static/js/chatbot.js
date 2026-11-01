const chatToggleBtn = document.getElementById('chat-toggle-btn');
const chatWindow = document.getElementById('chat-window');
const chatCloseBtn = document.getElementById('chat-close-btn');
const chatMessages = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const chatSendBtn = document.getElementById('chat-send-btn');
const micBtn = document.getElementById('chat-mic-btn');
const langSelect = document.getElementById('chat-lang-select');

const sessionId = 'session-' + Date.now();

/* =====================================================
   MARKDOWN HELPERS (NEW)
   - renderMarkdown: turns **bold**, lists, etc. into safe HTML
   - stripMarkdown: removes the symbols so text-to-speech
     does not read "star star"
   Uses marked + DOMPurify if they are loaded in the HTML page;
   otherwise falls back to a simple built-in converter.
===================================================== */

function renderMarkdown(text) {
  const source = text == null ? '' : String(text);

  if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
    const parse = typeof marked.parse === 'function' ? marked.parse : marked;
    return DOMPurify.sanitize(parse(source));
  }

  // Fallback: escape HTML first, then convert **bold**, *italic* and line breaks
  return source
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*(?!\s)(.+?)\*(?!\*)/g, '$1<em>$2</em>')
    .replace(/\n/g, '<br>');
}

function stripMarkdown(text) {
  return String(text == null ? '' : text)
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/(^|[^*])\*(?!\s)(.+?)\*(?!\*)/g, '$1$2')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^\s*[-*]\s+/gm, '')
    .replace(/`+/g, '');
}

chatToggleBtn.addEventListener('click', () => {
  chatWindow.classList.toggle('hidden');
});

chatCloseBtn.addEventListener('click', () => {
  chatWindow.classList.add('hidden');
});

chatSendBtn.addEventListener('click', sendMessage);

chatInput.addEventListener('keypress', (e) => {
  if (e.key === 'Enter') {
    sendMessage();
  }
});

function addMessage(text, sender) {
  const msgDiv = document.createElement('div');
  msgDiv.className = `chat-message ${sender}`;

  const textSpan = document.createElement('span');

  if (sender === 'bot') {
    // CHANGED: bot replies are rendered as Markdown (**bold** etc.)
    textSpan.innerHTML = renderMarkdown(text);
  } else {
    // User messages stay plain text so typed HTML can never be injected
    textSpan.textContent = text;
  }

  msgDiv.appendChild(textSpan);

  // Add a "Listen" button only to bot replies
  if (sender === 'bot') {
    const listenBtn = document.createElement('button');
    listenBtn.className = 'listen-btn';
    listenBtn.textContent = '🔊';
    listenBtn.title = 'Listen to this answer';
    listenBtn.addEventListener('click', () => speakText(text));
    msgDiv.appendChild(listenBtn);
  }

  chatMessages.appendChild(msgDiv);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return msgDiv;
}

async function sendMessage() {
  const message = chatInput.value.trim();
  if (!message) return;

  addMessage(message, 'user');
  chatInput.value = '';

  const thinkingMsg = addMessage('Thinking...', 'bot');

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: message,
        session_id: sessionId
      })
    });

    const data = await response.json();
    thinkingMsg.remove();

    addMessage(data.answer ?? 'Sorry, something went wrong.', 'bot');

  } catch (err) {
    thinkingMsg.remove();
    addMessage('Assistant is unavailable right now.', 'bot');
  }
}

/* =====================================================
   TEXT-TO-SPEECH (Listen button)
===================================================== */

function speakText(text) {
  if (!window.speechSynthesis) {
    alert("Sorry, this browser doesn't support reading answers aloud.");
    return;
  }
  window.speechSynthesis.cancel();

  // CHANGED: remove Markdown symbols so they are not read aloud
  const spokenText = stripMarkdown(text);

  const utterance = new SpeechSynthesisUtterance(spokenText);
  utterance.lang = detectSpeechLang(spokenText);
  window.speechSynthesis.speak(utterance);
}

function detectSpeechLang(text) {
  const hasDevanagari = /[\u0900-\u097F]/.test(text);
  return hasDevanagari ? "hi-IN" : "en-US";
}

/* =====================================================
   SPEECH-TO-TEXT (Mic button) — live text + multi-language
===================================================== */

function setupVoiceInput() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  if (!SpeechRecognition) {
    micBtn.disabled = true;
    micBtn.title = "Voice input not supported in this browser";
    return;
  }

  const recognition = new SpeechRecognition();
  recognition.interimResults = true;   // show live text while speaking
  recognition.continuous = false;
  recognition.maxAlternatives = 1;

  let isListening = false;
  let baseText = '';

  micBtn.addEventListener('click', () => {
    if (isListening) {
      recognition.stop();
      return;
    }

    recognition.lang = langSelect.value; // en-US / hi-IN / mr-IN
    baseText = chatInput.value ? chatInput.value + ' ' : '';

    isListening = true;
    micBtn.classList.add('listening');
    recognition.start();
  });

  recognition.onresult = (event) => {
    let transcript = '';
    for (let i = 0; i < event.results.length; i++) {
      transcript += event.results[i][0].transcript;
    }
    chatInput.value = baseText + transcript;
  };

  recognition.onerror = (event) => {
    console.error("Speech recognition error:", event.error);
    isListening = false;
    micBtn.classList.remove('listening');
  };

  recognition.onend = () => {
    isListening = false;
    micBtn.classList.remove('listening');
  };
}

setupVoiceInput();