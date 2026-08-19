"""Minimal chat UI served by FastAPI itself (no separate frontend process).

This is a single inline HTML page that talks to /v1/chat/completions over SSE.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.config import get_settings

router = APIRouter()


CHAT_HTML = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>@@BOT_NAME@@</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- Markdown renderer (GFM: tables, lists, headings) + sanitizer. Loaded
     synchronously so the renderText() defined further down can rely on
     globals `marked` and `DOMPurify` being present at first call. -->
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dompurify/dist/purify.min.js"></script>
<style>
  /* iPhone / iMessage-inspired theme */
  :root {
    --bg: #f2f2f7;                /* iOS systemGroupedBackground */
    --panel: rgba(255,255,255,0.78); /* translucent navbar */
    --panel-solid: #ffffff;
    --panel2: #ffffff;
    --field: #e9e9eb;             /* iOS field/secondary fill */
    --text: #1c1c1e;              /* iOS label */
    --text-soft: #3c3c43;
    --muted: #8e8e93;             /* iOS secondaryLabel / tertiaryLabel mix */
    --separator: rgba(60,60,67,0.18);
    --accent: #007aff;            /* iOS systemBlue */
    --accent-pressed: #0062cc;
    --user-bg-1: #2af;            /* iMessage blue gradient stops */
    --user-bg-2: #007aff;
    --user-fg: #ffffff;
    --assistant-bg: #e9e9eb;      /* iMessage gray bubble */
    --assistant-fg: #1c1c1e;
    --error: #ff3b30;             /* iOS systemRed */
    --shadow: 0 1px 2px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.06);
  }
  /* Forced light theme — do not follow system dark mode. */
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  html, body { height: 100%; margin: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font: 15px/1.45 -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro",
          "Segoe UI", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
    -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
    display: flex; flex-direction: column;
    letter-spacing: -0.01em;
  }
  /* iOS-style translucent navigation bar */
  header {
    padding: 10px 16px;
    background: var(--panel);
    -webkit-backdrop-filter: saturate(180%) blur(20px);
    backdrop-filter: saturate(180%) blur(20px);
    border-bottom: 0.5px solid var(--separator);
    display: flex; align-items: center; gap: 10px;
    flex-wrap: wrap;
    position: sticky; top: 0; z-index: 10;
  }
  header h1 {
    font-size: 17px; font-weight: 600; margin: 0;
    color: var(--text); letter-spacing: -0.02em;
  }
  header .meta { color: var(--muted); font-size: 12px; }
  header .spacer { flex: 1; }
  header input {
    background: var(--field); border: none;
    color: var(--text); padding: 7px 12px; border-radius: 999px;
    font: inherit; font-size: 13px; width: 220px;
  }
  header input::placeholder { color: var(--muted); }
  header input:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
  header button {
    background: transparent; color: var(--accent); border: none;
    padding: 6px 10px; border-radius: 8px; cursor: pointer;
    font: inherit; font-size: 14px; font-weight: 400;
  }
  header button:hover { background: rgba(0,122,255,0.08); }
  header button:active { background: rgba(0,122,255,0.16); }
  /* App body — sidebar (sessions) + chat column */
  .app {
    flex: 1; display: flex; min-height: 0;
  }
  .sidebar {
    width: 260px; min-width: 260px;
    background: var(--panel-solid);
    border-right: 0.5px solid var(--separator);
    display: flex; flex-direction: column;
    overflow: hidden;
  }
  .sidebar-head {
    padding: 12px 14px;
    border-bottom: 0.5px solid var(--separator);
    display: flex; align-items: center; justify-content: space-between;
    gap: 8px;
  }
  .sidebar-head .label {
    font-size: 12px; font-weight: 600; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.04em;
  }
  .sidebar-head button.new-chat {
    background: var(--accent); color: white; border: none;
    font: inherit; font-size: 13px; font-weight: 600;
    padding: 6px 12px; border-radius: 999px; cursor: pointer;
  }
  .sidebar-head button.new-chat:hover { background: var(--accent-pressed); }
  .session-list {
    list-style: none; margin: 0; padding: 6px 8px;
    overflow-y: auto; flex: 1;
  }
  .session-list .empty-msg {
    color: var(--muted); font-size: 13px; padding: 10px 8px;
    text-align: center;
  }
  .session-list li {
    padding: 9px 12px; border-radius: 10px;
    margin-bottom: 2px; cursor: pointer;
    display: grid;
    grid-template-columns: 1fr auto;
    grid-template-rows: auto auto;
    grid-template-areas: "title delete" "meta delete";
    column-gap: 6px;
    align-items: center;
    transition: background 0.08s ease;
  }
  .session-list li:hover { background: var(--field); }
  .session-list li:hover .delete-session { opacity: 1; }
  .session-list li.active { background: rgba(0,122,255,0.10); }
  .session-list li.active .session-title { color: var(--accent); font-weight: 600; }
  .session-list .session-title {
    grid-area: title;
    font-size: 13px; color: var(--text);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .session-list .session-meta {
    grid-area: meta;
    font-size: 11px; color: var(--muted);
  }
  .session-list .delete-session {
    grid-area: delete;
    background: transparent; border: none; cursor: pointer;
    color: var(--muted); font-size: 16px; line-height: 1;
    padding: 4px 6px; border-radius: 6px;
    opacity: 0; transition: opacity 0.08s ease, background 0.08s ease, color 0.08s ease;
  }
  .session-list li.active .delete-session { opacity: 0.7; }
  .session-list .delete-session:hover {
    background: rgba(255,59,48,0.12); color: #e55; opacity: 1;
  }
  .chat-column {
    flex: 1; display: flex; flex-direction: column;
    min-width: 0; min-height: 0;
  }
  main {
    flex: 1; overflow-y: auto; padding: 16px 14px 24px;
    display: flex; flex-direction: column; gap: 4px;
    max-width: 1100px; margin: 0 auto; width: 100%;
  }
  /* iMessage-style bubbles */
  .msg { display: flex; flex-direction: column; max-width: 78%; margin-top: 6px; }
  .msg.user { align-self: flex-end; align-items: flex-end; }
  .msg.assistant { align-self: flex-start; align-items: flex-start; }
  .msg .bubble {
    padding: 8px 14px; border-radius: 18px;
    white-space: pre-wrap; word-wrap: break-word;
    font-size: 15px; line-height: 1.35;
    box-shadow: 0 1px 0.5px rgba(0,0,0,0.06);
  }
  .msg.user .bubble {
    background: linear-gradient(180deg, var(--user-bg-1), var(--user-bg-2));
    color: var(--user-fg);
    border-bottom-right-radius: 4px;
  }
  .msg.assistant .bubble {
    background: var(--assistant-bg); color: var(--assistant-fg);
    border-bottom-left-radius: 4px;
  }
  .msg .progress {
    color: var(--muted); font-size: 12px; line-height: 1.55;
    background: var(--field);
    border-radius: 16px; padding: 8px 14px; margin-bottom: 4px;
    white-space: pre-wrap;
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    border-bottom-left-radius: 4px;
    max-width: 100%;
  }
  .msg .body { margin-top: 0; }
  .msg .body a { color: var(--accent); text-decoration: none; }
  .msg .body a:hover { text-decoration: underline; }
  .msg .body a.cite {
    font-size: 90%; font-weight: 600; padding: 0 2px; border-radius: 4px;
    background: rgba(120,120,128,0.14);
  }
  .msg .body a.cite:hover { background: rgba(120,120,128,0.28); text-decoration: none; }
  .msg .body strong { color: var(--text); font-weight: 600; }
  .msg.user .body strong { color: #ffffff; }
  .msg .body code {
    background: rgba(120,120,128,0.18); padding: 1px 5px;
    border-radius: 5px; font-size: 90%;
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  }
  .msg.user .body code { background: rgba(255,255,255,0.22); }
  .msg .body pre {
    background: rgba(120,120,128,0.12); padding: 10px;
    border-radius: 12px; overflow-x: auto;
    margin: 8px 0;
  }
  .msg .body pre code { background: none; padding: 0; font-size: 13px; }
  /* GFM block elements emitted by marked. The bubble's pre-wrap default
     would force a blank line between every block — disable inside body. */
  .msg .body { white-space: normal; }
  .msg .body p { margin: 0.4em 0; }
  .msg .body p:first-child { margin-top: 0; }
  .msg .body p:last-child { margin-bottom: 0; }
  .msg .body ul, .msg .body ol { margin: 0.4em 0; padding-left: 1.4em; }
  .msg .body li { margin: 0.15em 0; }
  .msg .body h1, .msg .body h2, .msg .body h3,
  .msg .body h4, .msg .body h5, .msg .body h6 {
    margin: 0.5em 0 0.3em; font-weight: 600;
  }
  .msg .body h1 { font-size: 1.15em; }
  .msg .body h2 { font-size: 1.08em; }
  .msg .body h3 { font-size: 1.02em; }
  .msg .body h4, .msg .body h5, .msg .body h6 { font-size: 1em; }
  .msg .body blockquote {
    margin: 0.4em 0; padding: 2px 10px;
    border-left: 3px solid var(--separator); color: var(--text-soft);
  }
  .msg .body hr { border: none; border-top: 1px solid var(--separator); margin: 0.6em 0; }
  .msg .body table {
    border-collapse: collapse; margin: 0.6em 0; font-size: 13.5px;
    display: block; overflow-x: auto; max-width: 100%;
  }
  .msg .body th, .msg .body td {
    border: 1px solid var(--separator);
    padding: 4px 8px; text-align: left; vertical-align: top;
  }
  .msg .body th {
    background: rgba(120,120,128,0.10); font-weight: 600;
  }
  /* iOS-style input footer */
  footer {
    padding: 8px 12px calc(12px + env(safe-area-inset-bottom));
    background: var(--panel);
    -webkit-backdrop-filter: saturate(180%) blur(20px);
    backdrop-filter: saturate(180%) blur(20px);
    border-top: 0.5px solid var(--separator);
  }
  .input-wrap {
    max-width: 1100px; margin: 0 auto;
    display: flex; gap: 8px; align-items: flex-end;
    background: var(--panel2);
    border: 1px solid var(--separator);
    border-radius: 22px;
    padding: 4px 4px 4px 14px;
  }
  textarea {
    flex: 1; resize: none; min-height: 32px; max-height: 200px;
    background: transparent; color: var(--text);
    border: none; padding: 8px 4px;
    font: inherit; font-size: 15px; line-height: 1.35;
  }
  textarea:focus { outline: none; }
  textarea::placeholder { color: var(--muted); }
  button.send {
    background: var(--accent); color: white; border: none;
    width: 34px; height: 34px; border-radius: 50%;
    cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; padding: 0;
    transition: transform 0.06s ease, background 0.12s ease;
  }
  button.send:hover { background: var(--accent-pressed); }
  button.send:active { transform: scale(0.94); }
  button.send:disabled { opacity: 0.4; cursor: not-allowed; }
  button.send::before { content: "↑"; font-weight: 700; line-height: 1; }
  /* Empty state */
  .empty {
    color: var(--muted); text-align: center; padding: 80px 20px;
  }
  .empty h2 { font-size: 22px; font-weight: 700; margin: 0 0 8px; color: var(--text); letter-spacing: -0.02em; }
  .empty p { margin: 4px 0; font-size: 14px; }
  .empty code {
    background: var(--field); padding: 1px 6px; border-radius: 5px;
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-size: 90%;
  }
  .err { color: var(--error); }

  /* Login screen — iOS modal card */
  #login-screen {
    flex: 1; display: flex; align-items: center; justify-content: center;
    padding: 20px;
    background: var(--bg);
  }
  #login-card {
    background: var(--panel-solid);
    border-radius: 18px; padding: 28px 24px;
    width: 100%; max-width: 360px;
    box-shadow: var(--shadow);
    border: 0.5px solid var(--separator);
  }
  #login-card h2 {
    margin: 0 0 6px; font-size: 22px; font-weight: 700;
    color: var(--text); text-align: center; letter-spacing: -0.02em;
  }
  #login-card p {
    margin: 0 0 22px; color: var(--muted);
    font-size: 13px; text-align: center; line-height: 1.4;
  }
  #login-card label {
    display: block; margin-bottom: 6px;
    color: var(--muted); font-size: 12px;
    font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em;
  }
  #login-card input {
    width: 100%; background: var(--field); color: var(--text);
    border: none; border-radius: 12px;
    padding: 12px 14px; font: inherit; font-size: 16px;
  }
  #login-card input:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
  #login-card button {
    margin-top: 16px; width: 100%; background: var(--accent);
    color: white; border: none; padding: 13px;
    border-radius: 12px; font: inherit; font-size: 16px;
    font-weight: 600; cursor: pointer;
    transition: background 0.12s ease, transform 0.06s ease;
  }
  #login-card button:hover { background: var(--accent-pressed); }
  #login-card button:active { transform: scale(0.985); }
  #login-card button:disabled { opacity: 0.5; cursor: not-allowed; }
  #login-card .hint {
    color: var(--error); font-size: 12px;
    margin-top: 10px; min-height: 16px; text-align: center;
  }

  /* First-login welcome modal — mirrors the iOS login card */
  #welcome-overlay {
    position: fixed; inset: 0; z-index: 100;
    display: none; align-items: center; justify-content: center;
    padding: 20px;
    background: rgba(0,0,0,0.28);
  }
  #welcome-card {
    background: var(--panel-solid);
    border-radius: 18px; padding: 28px 24px;
    width: 100%; max-width: 400px;
    box-shadow: var(--shadow);
    border: 0.5px solid var(--separator);
  }
  #welcome-card h2 {
    margin: 0 0 12px; font-size: 20px; font-weight: 700;
    color: var(--text); text-align: center; letter-spacing: -0.02em;
  }
  #welcome-card p {
    margin: 0 0 22px; color: var(--text-soft);
    font-size: 14px; line-height: 1.6; text-align: left;
  }
  #welcome-card button {
    width: 100%; background: var(--accent);
    color: white; border: none; padding: 13px;
    border-radius: 12px; font: inherit; font-size: 16px;
    font-weight: 600; cursor: pointer;
    transition: background 0.12s ease, transform 0.06s ease;
  }
  #welcome-card button:hover { background: var(--accent-pressed); }
  #welcome-card button:active { transform: scale(0.985); }

  /* iOS user pill in nav bar */
  header .user-pill {
    background: var(--field); color: var(--text);
    border: none;
    padding: 5px 11px; border-radius: 999px;
    font-size: 12px; font-weight: 500;
  }

  /* Mobile tweaks */
  @media (max-width: 760px) {
    .sidebar { width: 220px; min-width: 220px; }
  }
  @media (max-width: 520px) {
    header { padding: 10px 12px; gap: 8px; }
    header h1 { font-size: 16px; }
    header input { width: 140px; font-size: 12px; }
    header .meta { display: none; }
    main { padding: 12px 10px 18px; }
    .msg { max-width: 86%; }
    .sidebar { display: none; }
  }
</style>
</head>
<body>
  <!-- Login screen: shown when ?user_id=<id> is missing from the URL -->
  <div id="login-screen" style="display:none;">
    <div id="login-card">
      <h2>@@BOT_NAME@@</h2>
      <p>사용자 아이디를 입력하면 챗봇으로 진입합니다. 입력한 아이디는 URL 파라미터로 부착됩니다.</p>
      <form id="login-form" autocomplete="off">
        <label for="login-id">사용자 아이디</label>
        <input id="login-id" type="text" placeholder="아이디를 입력하세요" autocomplete="off" autofocus>
        <button type="submit">로그인</button>
        <div class="hint" id="login-hint"></div>
      </form>
    </div>
  </div>

  <!-- Chat UI: shown when ?user_id=<id> is present -->
  <header id="chat-header" style="display:none;">
    <h1>@@BOT_NAME@@</h1>
    <span class="spacer"></span>
    <span class="user-pill" id="user-pill"></span>
    <button id="clear">대화 초기화</button>
    <button id="logout">로그아웃</button>
  </header>
  <div class="app" id="app-body" style="display:none;">
    <aside class="sidebar" id="sidebar">
      <div class="sidebar-head">
        <span class="label">대화 목록</span>
        <button class="new-chat" id="new-chat-btn">+ 새 대화</button>
      </div>
      <ul class="session-list" id="session-list">
        <li class="empty-msg">로딩 중...</li>
      </ul>
    </aside>
    <div class="chat-column">
      <main id="chat">
        <div class="empty" id="empty"></div>
      </main>
      <footer id="chat-footer">
        <div class="input-wrap">
          <textarea id="input" rows="1" placeholder="질문을 입력하세요" aria-label="질문 입력 (Enter 전송, Shift+Enter 줄바꿈)"></textarea>
          <button class="send" id="send" aria-label="전송"></button>
        </div>
      </footer>
    </div>
  </div>

  <!-- First-login welcome modal: shown once per user_id (localStorage flag) -->
  <div id="welcome-overlay">
    <div id="welcome-card" role="dialog" aria-modal="true" aria-labelledby="welcome-title">
      <h2 id="welcome-title">환영합니다</h2>
      <p>안녕하세요! 이 챗봇은 사내 Confluence/Kafka/Elasticsearch 문서를 검색해 답변합니다. 처음 사용하시는 계정은 개인화를 위해 답변 출력 형태를 지정해주시면, 이를 바탕으로 더욱 정확하고 사용자님의 업무 스타일에 최적화된 답변을 제공해 드릴 수 있습니다.</p>
      <button id="welcome-close" type="button">시작하기</button>
    </div>
  </div>

<script>
(function() {
  // ── Login gate: require ?user_id=<id> in the URL ──
  const params = new URLSearchParams(window.location.search);
  const userId = (params.get('user_id') || '').trim();

  const loginScreen = document.getElementById('login-screen');
  const chatHeader = document.getElementById('chat-header');
  const appBody = document.getElementById('app-body');
  const chatMain = document.getElementById('chat');
  const sessionListEl = document.getElementById('session-list');
  const newChatBtn = document.getElementById('new-chat-btn');

  if (!userId) {
    loginScreen.style.display = 'flex';
    const form = document.getElementById('login-form');
    const idInput = document.getElementById('login-id');
    const hint = document.getElementById('login-hint');
    // Pre-fill with the last logged-in id, if any.
    try {
      const last = localStorage.getItem('rag-chat:lastUserId');
      if (last) idInput.value = last;
    } catch (e) {}
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const v = idInput.value.trim();
      if (!v) { hint.textContent = '아이디를 입력하세요.'; return; }
      if (!/^[A-Za-z0-9._-]{1,64}$/.test(v)) {
        hint.textContent = '영문/숫자/._- 만 사용 (최대 64자).';
        return;
      }
      try { localStorage.setItem('rag-chat:lastUserId', v); } catch (e) {}
      const url = new URL(window.location.href);
      url.searchParams.set('user_id', v);
      window.location.href = url.toString();
    });
    return; // Stop here — chat UI stays hidden until logged in.
  }

  // Show chat UI now that we have a user_id.
  chatHeader.style.display = '';
  appBody.style.display = '';

  // First-login welcome modal — shown once per user_id, then suppressed
  // via a localStorage flag so returning accounts never see it again.
  (function showWelcomeOnce() {
    const WELCOME_KEY = 'rag-chat:welcomed:' + userId;
    try {
      if (localStorage.getItem(WELCOME_KEY) === '1') return;
    } catch (e) {}
    const overlay = document.getElementById('welcome-overlay');
    const closeBtn = document.getElementById('welcome-close');
    overlay.style.display = 'flex';
    function dismiss() {
      overlay.style.display = 'none';
      try { localStorage.setItem(WELCOME_KEY, '1'); } catch (e) {}
    }
    closeBtn.addEventListener('click', dismiss);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) dismiss(); });
  })();

  const chat = chatMain;
  const empty = document.getElementById('empty');
  const input = document.getElementById('input');
  const sendBtn = document.getElementById('send');
  const clearBtn = document.getElementById('clear');
  const logoutBtn = document.getElementById('logout');
  const userPill = document.getElementById('user-pill');
  userPill.textContent = '👤 ' + userId;

  // Per-(user, session) message cache. Each session has its own key so
  // switching sessions doesn't blow away another's history.
  const SESSION_KEY = 'rag-chat:session:v1:' + userId;
  function messagesKey(sid) { return 'rag-chat:messages:v3:' + userId + ':' + sid; }

  function newSessionId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return window.crypto.randomUUID();
    }
    return 'sess-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
  }
  let sessionId;
  try {
    sessionId = localStorage.getItem(SESSION_KEY) || '';
  } catch (e) { sessionId = ''; }
  if (!sessionId) {
    sessionId = newSessionId();
    try { localStorage.setItem(SESSION_KEY, sessionId); } catch (e) {}
  }

  let messages = [];  // [{role, content}]
  function loadMessagesFromCache() {
    try {
      const saved = localStorage.getItem(messagesKey(sessionId));
      messages = saved ? JSON.parse(saved) : [];
    } catch (e) { messages = []; }
  }
  loadMessagesFromCache();

  function autosize() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 200) + 'px';
  }
  input.addEventListener('input', autosize);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  sendBtn.addEventListener('click', send);
  clearBtn.addEventListener('click', () => {
    if (messages.length && !confirm('현재 대화를 비우고 새 대화를 시작할까요?')) return;
    startNewSession();
  });
  newChatBtn.addEventListener('click', () => {
    if (messages.length && !confirm('현재 대화를 비우고 새 대화를 시작할까요?')) return;
    startNewSession();
  });
  logoutBtn.addEventListener('click', () => {
    if (!confirm('로그아웃 할까요? 현재 대화 기록은 다음 로그인 시 그대로 보입니다.')) return;
    const url = new URL(window.location.href);
    url.searchParams.delete('user_id');
    window.location.href = url.pathname + (url.search ? url.search : '');
  });

  function persist() {
    try { localStorage.setItem(messagesKey(sessionId), JSON.stringify(messages)); } catch (e) {}
  }

  // ── Sessions sidebar ──
  async function fetchSessions() {
    try {
      const r = await fetch('/v1/sessions?user_id=' + encodeURIComponent(userId));
      if (!r.ok) return [];
      const data = await r.json();
      return data.sessions || [];
    } catch (e) { return []; }
  }
  async function fetchSessionMessages(sid) {
    try {
      const r = await fetch(
        '/v1/sessions/' + encodeURIComponent(sid) + '/messages?user_id=' + encodeURIComponent(userId)
      );
      if (!r.ok) return [];
      const data = await r.json();
      return data.messages || [];
    } catch (e) { return []; }
  }
  function renderSessionList(sessions) {
    sessionListEl.innerHTML = '';
    // Always show the current session at the top, even if it has no logged
    // turns yet (so the user sees their active thread highlighted).
    const seen = new Set();
    const items = [];
    if (sessionId) {
      const cur = sessions.find(s => s.session_id === sessionId);
      if (cur) {
        items.push(cur); seen.add(sessionId);
      } else {
        items.push({ session_id: sessionId, title: '(새 대화)', turn_count: 0 });
        seen.add(sessionId);
      }
    }
    for (const s of sessions) {
      if (!seen.has(s.session_id)) items.push(s);
    }
    if (!items.length) {
      const li = document.createElement('li');
      li.className = 'empty-msg';
      li.textContent = '아직 대화가 없습니다.';
      sessionListEl.appendChild(li);
      return;
    }
    for (const s of items) {
      const li = document.createElement('li');
      if (s.session_id === sessionId) li.classList.add('active');
      const title = document.createElement('div');
      title.className = 'session-title';
      title.textContent = s.title || '(제목 없음)';
      li.appendChild(title);
      if (s.turn_count) {
        const meta = document.createElement('div');
        meta.className = 'session-meta';
        meta.textContent = s.turn_count + '턴';
        li.appendChild(meta);
      }
      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'delete-session';
      delBtn.title = '이 세션 삭제';
      delBtn.setAttribute('aria-label', '세션 삭제');
      delBtn.textContent = '×';
      delBtn.addEventListener('click', (ev) => {
        ev.stopPropagation();  // don't switch into the session we're deleting
        deleteSession(s.session_id, s.title || '(제목 없음)');
      });
      li.appendChild(delBtn);
      li.addEventListener('click', () => switchSession(s.session_id));
      sessionListEl.appendChild(li);
    }
  }
  async function deleteSession(sid, label) {
    if (!confirm('"' + label + '" 세션을 삭제할까요? 로그도 함께 지워집니다.')) return;
    try {
      const r = await fetch(
        '/v1/sessions/' + encodeURIComponent(sid) + '?user_id=' + encodeURIComponent(userId),
        { method: 'DELETE' }
      );
      if (!r.ok) {
        alert('삭제 실패: ' + (await r.text()));
        return;
      }
    } catch (e) {
      alert('삭제 중 오류: ' + e);
      return;
    }
    // Drop the local message cache for the deleted session.
    try { localStorage.removeItem(messagesKey(sid)); } catch (e) {}
    if (sid === sessionId) {
      // The active session was deleted — start a fresh one so the chat
      // column is never pointing at a vanished thread.
      startNewSession();
    } else {
      refreshSessionList();
    }
  }
  async function refreshSessionList() {
    const sessions = await fetchSessions();
    renderSessionList(sessions);
  }
  async function switchSession(sid) {
    if (sid === sessionId) return;
    sessionId = sid;
    try { localStorage.setItem(SESSION_KEY, sessionId); } catch (e) {}
    // Try local cache first, then fall back to server-stored history so
    // the user can resume a session from another device / browser.
    loadMessagesFromCache();
    if (!messages.length) {
      const serverMsgs = await fetchSessionMessages(sid);
      if (serverMsgs.length) {
        messages = serverMsgs;
        persist();
      }
    }
    rerenderHistory();
    refreshSessionList();
  }
  function startNewSession() {
    sessionId = newSessionId();
    try { localStorage.setItem(SESSION_KEY, sessionId); } catch (e) {}
    messages = [];
    persist();
    rerenderHistory();
    refreshSessionList();
  }
  // The intro message is rendered as a persistent assistant bubble at the top
  // of every chat. It is NOT added to `messages` (so it never gets sent to the
  // backend as history) but stays visible above the conversation forever —
  // streamed (typewriter) on first appearance, static on subsequent reloads.
  const INTRO_TEXT = '안녕하세요 저는 @@BOT_NAME@@입니다. 무엇을 도와드릴까요?';
  // Typewriter timer for the intro stream — must be cancellable so that if
  // the user sends a message mid-stream we don't keep ticking against a
  // detached DOM node.
  let introTimer = null;
  let introWrap = null;

  function cancelIntroStream() {
    if (introTimer) { clearTimeout(introTimer); introTimer = null; }
    introWrap = null;
  }

  // Force-finish any in-flight typewriter so the bubble is fully populated
  // before the user message lands beneath it. Keeps the intro bubble in the
  // DOM (does NOT remove it).
  function freezeIntro() {
    if (introTimer) { clearTimeout(introTimer); introTimer = null; }
    if (introWrap) {
      const b = introWrap.querySelector('.bubble.body');
      if (b) b.textContent = INTRO_TEXT;
    }
    introWrap = null;
  }

  function renderIntroStreaming() {
    cancelIntroStream();
    const wrap = document.createElement('div');
    wrap.className = 'msg assistant intro';
    const body = document.createElement('div');
    body.className = 'bubble body';
    wrap.appendChild(body);
    chat.appendChild(wrap);
    introWrap = wrap;
    // Typewriter stream: append one char per tick.
    let i = 0;
    const STEP_MS = 35;       // per-char delay
    const START_MS = 250;     // small initial pause so the bubble appears first
    const tick = () => {
      if (!introWrap) return; // cancelled
      if (i >= INTRO_TEXT.length) { introTimer = null; return; }
      body.textContent += INTRO_TEXT[i++];
      chat.scrollTop = chat.scrollHeight;
      introTimer = setTimeout(tick, STEP_MS);
    };
    introTimer = setTimeout(tick, START_MS);
  }

  function renderIntroStatic() {
    const wrap = document.createElement('div');
    wrap.className = 'msg assistant intro';
    const body = document.createElement('div');
    body.className = 'bubble body';
    body.textContent = INTRO_TEXT;
    wrap.appendChild(body);
    chat.appendChild(wrap);
  }

  function rerenderHistory() {
    cancelIntroStream();
    chat.innerHTML = '';
    if (!messages.length) {
      // Fresh chat — animate the greeting.
      renderIntroStreaming();
    } else {
      // Existing conversation — show the greeting instantly at the top,
      // then render messages below it. Greeting persists across turns.
      renderIntroStatic();
      for (const m of messages) renderMessage(m.role, m.content);
    }
  }

  // Tiny renderer: escape HTML, autolink http(s), **bold**, `code`, triple-backtick code blocks,
  // and inline citation tokens [N] mapped to source URLs via the CITES marker.
  function escapeHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }
  // Parse a trailing CITES marker out of the answer body. Returns the text
  // without the marker plus a {n: url} map so [N] tokens can be linked.
  function parseCites(text) {
    const m = text.match(/\\n?<!--CITES:(\\[[\\s\\S]*?\\])-->/);
    if (!m) return { stripped: text, cites: {} };
    let cites = {};
    try {
      const arr = JSON.parse(m[1]);
      for (const c of arr) {
        if (c && typeof c.n === 'number' && c.url) cites[c.n] = c.url;
      }
    } catch (e) { /* malformed marker — render as plain text */ }
    const stripped = text.slice(0, m.index) + text.slice(m.index + m[0].length);
    return { stripped, cites };
  }
  // Walk text nodes under `root` and convert `[N]` tokens into clickable
  // anchors using the {n: url} map. Text inside <a>/<code>/<pre> is left
  // alone so we don't double-link or mangle code samples.
  function linkCitations(root, cites) {
    if (!cites) return;
    const skip = { A: 1, CODE: 1, PRE: 1 };
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const parent = node.parentNode;
      if (!parent || skip[parent.tagName]) continue;
      const text = node.nodeValue;
      if (!text || text.indexOf('[') < 0) continue;
      const re = /\\[(\\d+)\\]/g;
      let m, last = 0, frag = null;
      while ((m = re.exec(text)) !== null) {
        const url = cites[+m[1]];
        if (!url) continue;
        if (!frag) frag = document.createDocumentFragment();
        if (m.index > last) {
          frag.appendChild(document.createTextNode(text.slice(last, m.index)));
        }
        const a = document.createElement('a');
        a.className = 'cite';
        a.href = url;
        a.target = '_blank';
        a.rel = 'noopener';
        a.textContent = m[0];
        frag.appendChild(a);
        last = m.index + m[0].length;
      }
      if (frag) {
        if (last < text.length) {
          frag.appendChild(document.createTextNode(text.slice(last)));
        }
        parent.replaceChild(frag, node);
      }
    }
  }

  // Full GFM markdown via marked, sanitized via DOMPurify. Tables, lists,
  // headings, blockquotes, code fences, autolinks, etc. all work. The
  // legacy mini-renderer is gone — this is now the single rendering path.
  function renderText(text, cites) {
    cites = cites || {};
    if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
      // CDN failed to load — fall back to escaped plaintext so chat at
      // least keeps showing the answer instead of breaking.
      return escapeHtml(text || '');
    }
    const rawHtml = marked.parse(text || '', { breaks: true, gfm: true });
    const cleanHtml = DOMPurify.sanitize(rawHtml, {
      ADD_ATTR: ['target', 'rel'],
    });
    const tmp = document.createElement('div');
    tmp.innerHTML = cleanHtml;
    linkCitations(tmp, cites);
    // Force external links to open in a new tab — marked's autolinks and
    // user-pasted urls don't get target=_blank otherwise.
    for (const a of tmp.querySelectorAll('a[href^="http"]')) {
      if (!a.target) a.target = '_blank';
      if (!a.rel) a.rel = 'noopener';
    }
    return tmp.innerHTML;
  }

  function renderMessage(role, content) {
    // (intro is cleared by send() before the first message lands here)
    const wrap = document.createElement('div');
    wrap.className = 'msg ' + role;
    if (role === 'assistant') {
      const progress = document.createElement('div');
      progress.className = 'progress';
      progress.style.display = 'none';
      const body = document.createElement('div');
      body.className = 'bubble body';
      const SEP = '\\n─────────────────────────────────────\\n';
      const idx = content.indexOf(SEP);
      if (idx >= 0) {
        progress.textContent = content.slice(0, idx).trim();
        const parsed = parseCites(content.slice(idx + SEP.length));
        body.innerHTML = renderText(parsed.stripped, parsed.cites);
        if (progress.textContent) progress.style.display = '';
      } else {
        progress.textContent = content.trim();
        if (progress.textContent) progress.style.display = '';
      }
      wrap.appendChild(progress);
      wrap.appendChild(body);
    } else {
      const body = document.createElement('div');
      body.className = 'bubble';
      body.textContent = content;
      wrap.appendChild(body);
    }
    chat.appendChild(wrap);
    return wrap;
  }

  function liveAssistantMessage() {
    // (intro is cleared by send() before the first message lands here)
    const wrap = document.createElement('div');
    wrap.className = 'msg assistant';
    const progress = document.createElement('div');
    progress.className = 'progress';
    progress.style.display = 'none';
    const body = document.createElement('div');
    body.className = 'bubble body';
    body.textContent = '…';
    wrap.appendChild(progress);
    wrap.appendChild(body);
    chat.appendChild(wrap);
    let buf = '';
    const SEP = '\\n─────────────────────────────────────\\n';
    function update(text) {
      buf += text;
      const idx = buf.indexOf(SEP);
      if (idx >= 0) {
        const before = buf.slice(0, idx).trim();
        const after = buf.slice(idx + SEP.length);
        progress.textContent = before;
        if (before) progress.style.display = '';
        const parsed = parseCites(after);
        body.innerHTML = renderText(parsed.stripped, parsed.cites);
      } else {
        progress.textContent = buf.trim();
        if (progress.textContent) progress.style.display = '';
        body.textContent = '';
      }
      chat.scrollTop = chat.scrollHeight;
    }
    function finalText() { return buf; }
    return { update, finalText, body };
  }

  rerenderHistory();
  chat.scrollTop = chat.scrollHeight;
  refreshSessionList();

  async function send() {
    const text = input.value.trim();
    if (!text) return;
    sendBtn.disabled = true;
    input.disabled = true;

    // First turn: freeze the streaming intro (don't remove it). The greeting
    // bubble stays at the top; the user message and answer land beneath it.
    if (messages.length === 0) freezeIntro();

    messages.push({ role: 'user', content: text });
    persist();
    renderMessage('user', text);
    input.value = '';
    autosize();
    chat.scrollTop = chat.scrollHeight;

    const live = liveAssistantMessage();
    chat.scrollTop = chat.scrollHeight;

    try {
      const headers = { 'Content-Type': 'application/json' };
      const resp = await fetch('/v1/chat/completions', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          model: 'rag-chatbot',
          messages: messages,
          stream: true,
          user_id: userId,
          session_id: sessionId,
        }),
      });
      if (!resp.ok || !resp.body) {
        const errText = await resp.text();
        live.body.innerHTML = '<span class="err">요청 실패: ' + escapeHtml(errText) + '</span>';
        return;
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let pending = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        pending += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = pending.indexOf('\\n\\n')) >= 0) {
          const raw = pending.slice(0, idx).trim();
          pending = pending.slice(idx + 2);
          if (!raw.startsWith('data:')) continue;
          const data = raw.slice(5).trim();
          if (data === '[DONE]') continue;
          try {
            const json = JSON.parse(data);
            const delta = (json.choices && json.choices[0] && json.choices[0].delta) || {};
            if (delta.content) live.update(delta.content);
          } catch (e) { /* ignore parse glitches */ }
        }
      }
      messages.push({ role: 'assistant', content: live.finalText() });
      persist();
      // Pick up the freshly logged turn — title appears for new sessions,
      // turn count increments for existing ones.
      refreshSessionList();
    } catch (e) {
      live.body.innerHTML = '<span class="err">네트워크 오류: ' + escapeHtml(String(e)) + '</span>';
    } finally {
      sendBtn.disabled = false;
      input.disabled = false;
      input.focus();
    }
  }
})();
</script>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse)
async def chat_ui() -> HTMLResponse:
    # Branding is substituted at request time rather than import time so a
    # changed CHATBOT_NAME takes effect on reload without a code change.
    html = CHAT_HTML.replace("@@BOT_NAME@@", get_settings().chatbot_name)
    return HTMLResponse(content=html)
