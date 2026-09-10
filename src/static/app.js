/**
 * Vectorless RAG Lecture Navigator Frontend Client Engine
 */

let player = null;
let isPlayerReady = false;
let currentVideoId = null;
let currentTree = null;
let ingestedVideos = [];
let queryMode = "single"; // "single" or "multi"

// YouTube IFrame API Ready Callback
function onYouTubeIframeAPIReady() {
  if (currentVideoId) {
    loadYouTubePlayer(currentVideoId);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initApp();
});

async function initApp() {
  setupEventListeners();
  await loadIngestedVideos();

  // Default select first video if available
  if (ingestedVideos.length > 0) {
    await selectVideo(ingestedVideos[0].video_id);
  }
}

function setupEventListeners() {
  const ingestForm = document.getElementById("ingestForm");
  ingestForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const urlInput = document.getElementById("urlInput").value.trim();
    if (urlInput) {
      await processVideoUrl(urlInput);
    }
  });

  const queryForm = document.getElementById("queryForm");
  queryForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("queryInput");
    const question = input.value.trim();
    if (question) {
      if (queryMode === "single" && !currentVideoId) {
        alert("Please select or ingest a lecture video first!");
        return;
      }
      input.value = "";
      await handleUserQuery(question);
    }
  });
}

function setQueryMode(mode) {
  queryMode = mode;
  const singleBtn = document.getElementById("modeSingleBtn");
  const multiBtn = document.getElementById("modeMultiBtn");

  if (mode === "multi") {
    singleBtn.classList.remove("active");
    multiBtn.classList.add("active");
    loadChatHistory("all");
  } else {
    multiBtn.classList.remove("active");
    singleBtn.classList.add("active");
    if (currentVideoId) {
      loadChatHistory(currentVideoId);
    }
  }
}

// Fetch & Render Ingested Videos Library
async function loadIngestedVideos() {
  try {
    const res = await fetch("/api/videos");
    if (!res.ok) return;
    ingestedVideos = await res.json();
    
    // Fallback to sample API if library is empty
    if (ingestedVideos.length === 0) {
      const sampleRes = await fetch("/api/samples");
      if (sampleRes.ok) {
        const samples = await sampleRes.json();
        ingestedVideos = samples.map((s) => ({
          video_id: s.video_id,
          title: s.title,
          channel: s.channel,
          duration: s.duration,
          thumbnail_url: s.thumbnail_url,
          status: "ready",
          section_count: 5,
        }));
      }
    }

    renderLibraryCards();
  } catch (err) {
    console.error("Failed to load video library:", err);
  }
}

function renderLibraryCards() {
  const container = document.getElementById("samplesGrid");
  const statsEl = document.getElementById("libraryStats");
  container.innerHTML = "";

  statsEl.innerText = `${ingestedVideos.length} Lecture${ingestedVideos.length === 1 ? "" : "s"} Ingested`;

  if (ingestedVideos.length === 0) {
    container.innerHTML = `
      <div class="empty-library">
        <i class="fa-solid fa-film"></i>
        <p>No ingested lectures yet. Paste a YouTube URL below to process your first video!</p>
      </div>
    `;
    return;
  }

  ingestedVideos.forEach((video) => {
    const card = document.createElement("div");
    const isActive = video.video_id === currentVideoId;
    card.className = `sample-card ${isActive ? "active" : ""}`;
    card.id = `video_card_${video.video_id}`;

    const durMin = Math.round(video.duration / 60);

    card.innerHTML = `
      <div class="sample-card-body" onclick="selectVideo('${video.video_id}')">
        <img src="${video.thumbnail_url}" alt="${escapeHtml(video.title)}" class="sample-thumb" />
        <div class="sample-info">
          <h4>${escapeHtml(video.title)}</h4>
          <p><i class="fa-solid fa-user-gear"></i> ${escapeHtml(video.channel)} • ${durMin}m • ${video.section_count || 0} sections</p>
        </div>
      </div>
      <button class="delete-vid-btn" title="Delete Lecture" onclick="deleteVideo('${video.video_id}', event)">
        <i class="fa-solid fa-trash-can"></i>
      </button>
    `;

    container.appendChild(card);
  });
}

async function selectVideo(videoId) {
  currentVideoId = videoId;

  // Update active state in cards
  document.querySelectorAll(".sample-card").forEach((c) => c.classList.remove("active"));
  const activeCard = document.getElementById(`video_card_${videoId}`);
  if (activeCard) activeCard.classList.add("active");

  // Update URL input placeholder
  document.getElementById("urlInput").value = `https://www.youtube.com/watch?v=${videoId}`;
  
  // Load Player
  loadYouTubePlayer(videoId);

  // Load Tree
  await fetchAndRenderTree(videoId);

  // Load saved Q&A Chat History
  if (queryMode === "single") {
    await loadChatHistory(videoId);
  }
}

async function deleteVideo(videoId, event) {
  if (event) event.stopPropagation();
  if (!confirm("Are you sure you want to delete this lecture and its chat history?")) return;

  try {
    const res = await fetch(`/api/videos/${videoId}`, { method: "DELETE" });
    if (!res.ok) {
      alert("Failed to delete video.");
      return;
    }

    if (currentVideoId === videoId) {
      currentVideoId = null;
      currentTree = null;
      document.getElementById("treeContainer").innerHTML = `
        <div class="empty-tree-state">
          <i class="fa-solid fa-diagram-project"></i>
          <p>Topic hierarchy will appear here once a video is loaded.</p>
        </div>
      `;
    }

    await loadIngestedVideos();
    if (!currentVideoId && ingestedVideos.length > 0) {
      selectVideo(ingestedVideos[0].video_id);
    }
  } catch (err) {
    alert(`Error deleting video: ${err.message}`);
  }
}

let pendingVideoId = null;

function loadYouTubePlayer(videoId) {
  const placeholder = document.getElementById("playerPlaceholder");
  if (placeholder) placeholder.classList.add("hidden");

  if (!videoId) return;

  if (player && isPlayerReady && typeof player.loadVideoById === "function") {
    try {
      player.loadVideoById(videoId);
    } catch (err) {
      console.warn("Failed player.loadVideoById:", err);
    }
  } else if (!player) {
    pendingVideoId = videoId;
    isPlayerReady = false;
    try {
      if (window.YT && window.YT.Player) {
        player = new YT.Player("youtubePlayer", {
          height: "100%",
          width: "100%",
          videoId: videoId,
          playerVars: {
            autoplay: 0,
            modestbranding: 1,
            rel: 0,
          },
          events: {
            onReady: (event) => {
              isPlayerReady = true;
              if (pendingVideoId) {
                try {
                  event.target.loadVideoById(pendingVideoId);
                } catch (e) {}
                pendingVideoId = null;
              }
            },
          },
        });
      }
    } catch (err) {
      console.warn("Error initializing YT.Player:", err);
    }
  } else {
    // Player exists but is not ready yet: update pending target
    pendingVideoId = videoId;
  }
}

function seekToTimestamp(seconds, targetVideoId = null) {
  if (targetVideoId && targetVideoId !== currentVideoId) {
    selectVideo(targetVideoId).then(() => {
      setTimeout(() => executeSeek(seconds), 800);
    });
    return;
  }
  executeSeek(seconds);
}

function executeSeek(seconds) {
  const numSec = parseFloat(seconds);
  if (isNaN(numSec)) return;

  if (player && typeof player.seekTo === "function") {
    player.seekTo(numSec, true);
    if (typeof player.playVideo === "function") {
      player.playVideo();
    }
  }

  // Highlight active segment in Topic Tree
  highlightTreeSectionForTime(numSec);
}

function highlightTreeSectionForTime(seconds) {
  if (!currentTree || !currentTree.sections) return;

  let matchedNodeId = null;
  for (const sec of currentTree.sections) {
    if (seconds >= sec.start_ts && seconds <= (sec.end_ts || Infinity)) {
      matchedNodeId = sec.id;
      for (const sub of sec.subsections) {
        if (seconds >= sub.start_ts && seconds <= (sub.end_ts || Infinity)) {
          matchedNodeId = sub.id;
          break;
        }
      }
      break;
    }
  }

  if (matchedNodeId) {
    highlightTreeNodes([matchedNodeId]);
  }
}

// Ingestion Form Handler (Supports single & batch comma-separated URLs)
async function processVideoUrl(rawInput) {
  const urls = rawInput
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);

  if (urls.length === 0) return;

  for (let i = 0; i < urls.length; i++) {
    const url = urls[i];
    const pct = Math.round(((i + 0.5) / urls.length) * 100);
    showIngestStatus(`Ingesting (${i + 1}/${urls.length}): Building Topic Tree...`, pct);

    try {
      const res = await fetch("/api/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });

      if (!res.ok) {
        const err = await res.json();
        alert(`Ingestion Error for '${url}': ${err.detail}`);
        continue;
      }

      const data = await res.json();
      currentVideoId = data.video_id;
    } catch (err) {
      alert(`Failed to ingest video '${url}': ${err.message}`);
    }
  }

  showIngestStatus("All Videos Processed!", 100);
  setTimeout(hideIngestStatus, 1500);

  await loadIngestedVideos();
  if (currentVideoId) {
    await selectVideo(currentVideoId);
  }
}

function showIngestStatus(msg, percent) {
  const statusCard = document.getElementById("ingestStatus");
  const statusText = document.getElementById("statusText");
  const progressBar = document.getElementById("progressBar");

  statusCard.classList.remove("hidden");
  statusText.innerText = msg;
  progressBar.style.width = `${percent}%`;
}

function hideIngestStatus() {
  document.getElementById("ingestStatus").classList.add("hidden");
}

// Fetch & Render Topic Tree
async function fetchAndRenderTree(videoId) {
  try {
    const res = await fetch(`/api/tree/${videoId}`);
    if (!res.ok) return;
    currentTree = await res.json();

    document.getElementById("treeStats").innerText = `${currentTree.sections.length} Sections`;
    renderTopicTree(currentTree);
  } catch (err) {
    console.error("Failed to fetch topic tree:", err);
  }
}

function renderTopicTree(tree) {
  const container = document.getElementById("treeContainer");
  container.innerHTML = "";

  tree.sections.forEach((sec) => {
    const secEl = document.createElement("div");
    secEl.className = "tree-section";
    secEl.id = `tree_node_${sec.id}`;

    const startMin = formatTime(sec.start_ts);
    const endMin = formatTime(sec.end_ts);

    let subItemsHtml = sec.subsections
      .map((sub) => {
        const subStart = formatTime(sub.start_ts);
        const subEnd = formatTime(sub.end_ts);
        return `
          <div class="tree-sub-item" id="tree_node_${sub.id}" onclick="seekToTimestamp(${sub.start_ts}, '${tree.video_id}')">
            <div class="sub-header">
              <span>${escapeHtml(sub.title)}</span>
              <span class="ts-badge">${subStart} - ${subEnd}</span>
            </div>
            <p class="sub-summary">${escapeHtml(sub.summary)}</p>
          </div>
        `;
      })
      .join("");

    secEl.innerHTML = `
      <div class="tree-section-header" onclick="seekToTimestamp(${sec.start_ts}, '${tree.video_id}')">
        <div class="section-title-group">
          <i class="fa-solid fa-folder-open"></i>
          <span class="sec-title">${escapeHtml(sec.title)}</span>
        </div>
        <span class="ts-badge">${startMin} - ${endMin}</span>
      </div>
      <div class="tree-subsections">
        ${subItemsHtml}
      </div>
    `;

    container.appendChild(secEl);
  });
}

function renderQuestionSuggestions(questions) {
  const container = document.getElementById("suggestionsPills");
  container.innerHTML = "";

  questions.forEach((q) => {
    const pill = document.createElement("div");
    pill.className = "pill";
    pill.innerText = q;
    pill.onclick = () => {
      document.getElementById("queryInput").value = q;
      handleUserQuery(q);
    };
    container.appendChild(pill);
  });
}

// User Query Execution
async function handleUserQuery(question) {
  appendUserMessage(question);
  const loadingBubble = appendAssistantLoading();

  const targetVidId = queryMode === "multi" ? "all" : currentVideoId;

  try {
    const res = await fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        video_id: targetVidId,
        question: question,
      }),
    });

    loadingBubble.remove();

    if (!res.ok) {
      const err = await res.json();
      appendAssistantMessage(`Error executing vectorless query: ${err.detail}`);
      return;
    }

    const data = await res.json();
    appendAssistantResponse(data);

    if (queryMode === "single") {
      highlightTreeNodes(data.selected_nodes);
    }
  } catch (err) {
    loadingBubble.remove();
    appendAssistantMessage(`Connection failure: ${err.message}`);
  }
}

// Load Chat History from SQLite
async function loadChatHistory(videoId) {
  try {
    const res = await fetch(`/api/history/${videoId}`);
    if (!res.ok) return;
    const historyItems = await res.json();
    renderChatHistory(historyItems);
  } catch (err) {
    console.error("Failed to load chat history:", err);
  }
}

function renderChatHistory(items) {
  const chatHistory = document.getElementById("chatHistory");
  chatHistory.innerHTML = `
    <div class="welcome-chat">
      <div class="ai-avatar"><i class="fa-solid fa-brain"></i></div>
      <div class="welcome-body">
        <h4>Welcome to Vectorless RAG Navigation</h4>
        <p>Using <strong>hierarchical topic-tree LLM reasoning</strong> to navigate lecture content without chunking or vector embeddings.</p>
      </div>
    </div>
  `;

  items.forEach((item) => {
    appendUserMessage(item.question);
    appendAssistantResponse({
      answer: item.answer,
      selected_nodes: item.selected_nodes,
      rationale: item.rationale,
      timestamps: item.timestamps,
    });
  });
}

async function clearChatHistoryUI() {
  const targetId = queryMode === "multi" ? "all" : currentVideoId;
  await fetch(`/api/history?video_id=${targetId}`, { method: "DELETE" });
  renderChatHistory([]);
}

function appendUserMessage(text) {
  const chatHistory = document.getElementById("chatHistory");
  const msgEl = document.createElement("div");
  msgEl.className = "message message-user";
  msgEl.innerHTML = `<div class="message-bubble">${escapeHtml(text)}</div>`;
  chatHistory.appendChild(msgEl);
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

function appendAssistantLoading() {
  const chatHistory = document.getElementById("chatHistory");
  const msgEl = document.createElement("div");
  msgEl.className = "message message-assistant";
  msgEl.innerHTML = `
    <div class="ai-avatar"><i class="fa-solid fa-microchip"></i></div>
    <div class="message-bubble">
      <span class="rationale-tag"><i class="fa-solid fa-spinner fa-spin"></i> Step 1: Branch Selection (Topic Tree Summaries) → Step 2: Answer Synthesis...</span>
    </div>
  `;
  chatHistory.appendChild(msgEl);
  chatHistory.scrollTop = chatHistory.scrollHeight;
  return msgEl;
}

function appendAssistantResponse(data) {
  const chatHistory = document.getElementById("chatHistory");
  const msgEl = document.createElement("div");
  msgEl.className = "message message-assistant";

  const selectedNodesStr = data.selected_nodes ? data.selected_nodes.join(", ") : "";
  const rationaleStr = data.rationale ? escapeHtml(data.rationale) : "Vectorless RAG Tree Traversal";

  // Sources badge for multi-video
  let sourcesHtml = "";
  if (data.sources && data.sources.length > 0) {
    sourcesHtml = `<div class="sources-badge"><i class="fa-solid fa-book-bookmark"></i> Sources: ${data.sources.map(s => escapeHtml(s)).join(" • ")}</div>`;
  }

  // Parse inline text timestamps (e.g. 01:23, [01:23], (85s)) into clickable buttons
  const formattedAnswer = linkifyTimestamps(data.answer, currentVideoId);

  // Bottom timestamp pill buttons
  let tsHtml = "";
  if (data.timestamps && data.timestamps.length > 0) {
    tsHtml = `
      <div class="timestamp-links">
        ${data.timestamps
          .map((ts) => {
            const vidId = ts.video_id || currentVideoId;
            return `
              <button class="ts-link" onclick="seekToTimestamp(${ts.start_ts}, '${vidId}')">
                <i class="fa-solid fa-play"></i> ${formatTime(ts.start_ts)} - ${escapeHtml(ts.label)}
              </button>
            `;
          })
          .join("")}
      </div>
    `;
  }

  msgEl.innerHTML = `
    <div class="ai-avatar"><i class="fa-solid fa-brain"></i></div>
    <div class="message-bubble">
      ${sourcesHtml}
      <span class="rationale-tag">
        <i class="fa-solid fa-diagram-next"></i> Selected Branches: [${selectedNodesStr}] • Rationale: ${rationaleStr}
      </span>
      <p class="answer-text">${formattedAnswer}</p>
      ${tsHtml}
    </div>
  `;

  chatHistory.appendChild(msgEl);
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

function appendAssistantMessage(text) {
  const chatHistory = document.getElementById("chatHistory");
  const msgEl = document.createElement("div");
  msgEl.className = "message message-assistant";
  msgEl.innerHTML = `
    <div class="ai-avatar"><i class="fa-solid fa-brain"></i></div>
    <div class="message-bubble"><p>${escapeHtml(text)}</p></div>
  `;
  chatHistory.appendChild(msgEl);
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

/**
 * Smart Inline Timestamp Linkifier
 * Converts timestamps in text like [01:23], (01:23), 01:23, or 85s into clickable inline buttons.
 */
function linkifyTimestamps(text, videoId) {
  if (!text) return "";
  const escaped = escapeHtml(text);

  // Match pattern: MM:SS or HH:MM:SS or [MM:SS] or (MM:SS) or NNs
  return escaped.replace(/(\[?\(?(\d{1,2}:)?\d{1,2}:\d{2}\)?\]?)|(\b\d{2,4}\s*s\b)/gi, (match) => {
    let clean = match.replace(/[\[\]\(\)]/g, "").trim();
    let seconds = parseTimestampToSeconds(clean);
    if (seconds === null) return match;

    return `<button class="inline-ts-btn" onclick="seekToTimestamp(${seconds}, '${videoId}')"><i class="fa-solid fa-play"></i> ${clean}</button>`;
  });
}

function parseTimestampToSeconds(str) {
  if (str.endsWith("s") || str.endsWith("S")) {
    const val = parseFloat(str);
    return isNaN(val) ? null : val;
  }
  const parts = str.split(":").map((p) => parseInt(p, 10));
  if (parts.some((p) => isNaN(p))) return null;
  if (parts.length === 2) {
    return parts[0] * 60 + parts[1];
  } else if (parts.length === 3) {
    return parts[0] * 3600 + parts[1] * 60 + parts[2];
  }
  return null;
}

function highlightTreeNodes(nodeIds) {
  document.querySelectorAll(".tree-section, .tree-sub-item").forEach((el) => {
    el.classList.remove("highlighted");
  });

  nodeIds.forEach((id) => {
    // Handle 'video_id:node_id' or 'node_id'
    const cleanId = id.includes(":") ? id.split(":")[1] : id;
    const el = document.getElementById(`tree_node_${cleanId}`);
    if (el) {
      el.classList.add("highlighted");
      el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  });
}

function formatTime(seconds) {
  const sec = Math.floor(seconds);
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

function escapeHtml(text) {
  if (!text) return "";
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
