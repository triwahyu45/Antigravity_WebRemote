// ==========================================================================
// ULTIMATE ANTIGRAVITY CONTROLLER (Live Status, 2-Way Chat, Modal Viewer)
// ==========================================================================

const ACTIVE_ID = "63fb64ac-9344-46a1-8d60-a891ba0835d8";
let currentSessionId = localStorage.getItem("current_session_id") || ACTIVE_ID;
let socket = null;

document.addEventListener("DOMContentLoaded", () => {
    initUI();
    loadProjectsTree();
    loadSessionSteps(currentSessionId);
    loadSessionDetails(currentSessionId);
    initWebSocket();
    initChatSender();
});

function initUI() {
    const leftSidebar = document.getElementById("left-sidebar");
    const rightSidebar = document.getElementById("right-sidebar");
    const backdropLeft = document.getElementById("backdrop-left");
    const backdropRight = document.getElementById("backdrop-right");
    const backdropModal = document.getElementById("backdrop-modal");
    const artifactModal = document.getElementById("artifact-modal");

    const btnToggleLeft = document.getElementById("btn-toggle-left");
    const btnToggleRight = document.getElementById("btn-toggle-right");
    const btnCloseRight = document.getElementById("btn-close-right");
    const btnCloseModal = document.getElementById("btn-close-modal");
    const btnNewChat = document.getElementById("btn-new-chat");

    btnToggleLeft.addEventListener("click", () => {
        leftSidebar.classList.add("open");
        backdropLeft.classList.add("active");
    });

    btnToggleRight.addEventListener("click", () => {
        rightSidebar.classList.add("open");
        backdropRight.classList.add("active");
    });

    backdropLeft.addEventListener("click", closeSidebars);
    backdropRight.addEventListener("click", closeSidebars);
    backdropModal.addEventListener("click", closeModal);

    if (btnCloseRight) btnCloseRight.addEventListener("click", closeSidebars);
    if (btnCloseModal) btnCloseModal.addEventListener("click", closeModal);

    btnNewChat.addEventListener("click", () => {
        currentSessionId = ACTIVE_ID;
        localStorage.setItem("current_session_id", currentSessionId);
        closeSidebars();
        loadProjectsTree();
        loadSessionSteps(currentSessionId);
    });

    function closeSidebars() {
        leftSidebar.classList.remove("open");
        rightSidebar.classList.remove("open");
        backdropLeft.classList.remove("active");
        backdropRight.classList.remove("active");
    }

    function closeModal() {
        artifactModal.classList.remove("open");
        backdropModal.classList.remove("active");
    }
}

// 2-WAY CHAT SENDER
function initChatSender() {
    const promptInput = document.getElementById("chat-prompt");
    const btnSend = document.getElementById("btn-send");
    const btnMic = document.getElementById("btn-mic");

    btnSend.addEventListener("click", handleSend);
    promptInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    });

    // Voice Input (STT)
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        const recognizer = new SpeechRecognition();
        recognizer.lang = 'id-ID';
        recognizer.continuous = false;

        btnMic.addEventListener("click", () => {
            btnMic.classList.add("recording");
            recognizer.start();
        });

        recognizer.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            promptInput.value = transcript;
            btnMic.classList.remove("recording");
        };

        recognizer.onerror = () => btnMic.classList.remove("recording");
        recognizer.onend = () => btnMic.classList.remove("recording");
    }

    async function handleSend() {
        const text = promptInput.value.trim();
        if (!text) return;

        // Optimistic UI Append
        appendUserMessage(text);
        promptInput.value = "";

        // Trigger Live Working State in UI
        updateEngineBadge({ status: "working", current_action: "Sending prompt to Antigravity..." });

        try {
            await fetch("/api/chat/send", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: text, session_id: currentSessionId })
            });
        } catch (e) {
            console.error("Failed to send message:", e);
        }
    }
}

function appendUserMessage(text) {
    const container = document.getElementById("feed-container");
    const row = document.createElement("div");
    row.className = "feed-row user";
    row.innerHTML = `<div class="user-bubble">${escapeHtml(text)}</div>`;
    container.appendChild(row);
    scrollToBottom();
}

// WEBSOCKET REAL-TIME SYNC & STATUS
function initWebSocket() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${proto}//${window.location.host}/ws/stream`;
    
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log("⚡ WebSocket Live Connected to Antigravity");
    };

    socket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.event === "transcript_update" && data.session_id === currentSessionId) {
                renderSteps(data.items);
                if (data.engine_state) updateEngineBadge(data.engine_state);
            } else if (data.event === "status_heartbeat") {
                if (data.engine_state) updateEngineBadge(data.engine_state);
            }
        } catch (e) {
            console.error("WS Error:", e);
        }
    };

    socket.onclose = () => {
        setTimeout(initWebSocket, 2000);
    };
}

function updateEngineBadge(state) {
    const badge = document.getElementById("live-engine-badge");
    const text = document.getElementById("engine-status-text");
    const runningCard = document.getElementById("live-running-card");
    const runningAction = document.getElementById("running-action-text");
    const runningTimer = document.getElementById("running-timer-text");

    if (state.status === "working") {
        badge.className = "status-indicator-badge working";
        text.textContent = "Working";
        runningCard.classList.remove("hidden");
        runningAction.textContent = state.current_action || "Antigravity is working...";
        runningTimer.textContent = `Worked for ${state.elapsed_seconds || 0}s`;
    } else {
        badge.className = "status-indicator-badge idle";
        text.textContent = "Idle";
        runningCard.classList.add("hidden");
    }
}

// PROJECTS TREE
async function loadProjectsTree() {
    try {
        const res = await fetch("/api/projects");
        const data = await res.json();
        const treeEl = document.getElementById("projects-tree");
        treeEl.innerHTML = "";

        if (data.engine_state) updateEngineBadge(data.engine_state);

        data.projects.forEach(proj => {
            const group = document.createElement("div");
            group.className = "project-group";

            const title = document.createElement("div");
            title.className = "project-folder-title";
            title.innerHTML = `<i class="fas fa-folder text-sub"></i> ${proj.name}`;
            group.appendChild(title);

            proj.conversations.forEach(conv => {
                const item = document.createElement("div");
                item.className = `conv-item ${conv.id === currentSessionId ? "active" : ""}`;
                item.innerHTML = `<span>${conv.title}</span> <span class="time-badge">${conv.time}</span>`;
                
                item.addEventListener("click", () => {
                    currentSessionId = conv.id;
                    localStorage.setItem("current_session_id", currentSessionId);
                    document.getElementById("header-chat").textContent = conv.title;
                    document.getElementById("header-project").textContent = proj.name;
                    
                    document.getElementById("left-sidebar").classList.remove("open");
                    document.getElementById("backdrop-left").classList.remove("active");
                    
                    loadProjectsTree();
                    loadSessionSteps(currentSessionId);
                    loadSessionDetails(currentSessionId);
                });

                group.appendChild(item);
            });

            treeEl.appendChild(group);
        });
    } catch (e) {
        console.error("Tree error:", e);
    }
}

// LOAD STEPS & RENDER ARTIFACT PILLS
let renderedCount = 0;

async function loadSessionSteps(sessionId) {
    try {
        const res = await fetch(`/api/sessions/${sessionId}/steps`);
        const steps = await res.json();
        renderSteps(steps, true);
    } catch (e) {
        console.error("Steps error:", e);
    }
}

function renderSteps(steps, forceScroll = false) {
    const container = document.getElementById("feed-container");
    if (steps.length === renderedCount && !forceScroll) return;

    container.innerHTML = "";
    renderedCount = steps.length;

    steps.forEach(step => {
        const row = document.createElement("div");
        row.className = `feed-row ${step.type}`;

        if (step.type === "user") {
            row.innerHTML = `<div class="user-bubble">${escapeHtml(step.text)}</div>`;
        } else if (step.type === "tool_call") {
            row.innerHTML = `
                <i class="fas fa-bolt tool-icon text-cyan"></i>
                <span class="tool-name">${escapeHtml(step.name)}</span>
                <span class="tool-summary">: ${escapeHtml(step.summary)}</span>`;
        } else if (step.type === "assistant") {
            const body = document.createElement("div");
            body.className = "assistant-body";
            body.innerHTML = marked.parse(step.text);

            body.querySelectorAll("pre code").forEach((el) => {
                hljs.highlightElement(el);
            });

            const footer = document.createElement("div");
            footer.className = "assistant-footer";
            footer.innerHTML = `
                <span>10:40 PM</span>
                <div class="actions">
                    <i class="far fa-copy" title="Copy"></i>
                    <i class="far fa-thumbs-up" title="Like"></i>
                    <i class="far fa-thumbs-down" title="Dislike"></i>
                </div>`;

            row.appendChild(body);
            row.appendChild(footer);
        }

        container.appendChild(row);
    });

    scrollToBottom();
}

// LOAD RIGHT PANEL & ARTIFACT CLICK VIEWER
async function loadSessionDetails(sessionId) {
    try {
        const res = await fetch(`/api/sessions/${sessionId}/details`);
        const data = await res.json();

        // Files
        document.getElementById("count-files").textContent = data.files_changed.length;
        const filesEl = document.getElementById("files-changed-list");
        filesEl.innerHTML = "";
        data.files_changed.slice(0, 6).forEach(f => {
            const item = document.createElement("div");
            item.className = "file-item";
            item.innerHTML = `<i class="far fa-file-lines text-muted"></i> ${f}`;
            filesEl.appendChild(item);
        });

        // Artifacts (Clickable Modal!)
        document.getElementById("count-artifacts").textContent = data.artifacts_count;
        const artsEl = document.getElementById("artifacts-list");
        artsEl.innerHTML = "";
        data.artifacts.slice(0, 6).forEach(a => {
            const item = document.createElement("div");
            item.className = "artifact-item";
            item.innerHTML = `<i class="fas fa-book-open text-muted"></i> ${a}`;
            item.addEventListener("click", () => openArtifactModal(a));
            artsEl.appendChild(item);
        });

        // Uploads
        document.getElementById("count-uploads").textContent = data.uploads_count;
        const upEl = document.getElementById("uploads-list");
        upEl.innerHTML = "";
        data.uploads.slice(0, 4).forEach(u => {
            const item = document.createElement("div");
            item.className = "upload-item";
            item.innerHTML = `<i class="far fa-image text-muted"></i> ${u}`;
            upEl.appendChild(item);
        });
    } catch (e) {
        console.error("Details error:", e);
    }
}

// OPEN ARTIFACT MODAL
async function openArtifactModal(artifactName) {
    const modal = document.getElementById("artifact-modal");
    const backdrop = document.getElementById("backdrop-modal");
    const titleEl = document.getElementById("modal-art-title");
    const bodyEl = document.getElementById("modal-art-body");

    titleEl.innerHTML = `<i class="fas fa-book-open text-cyan"></i> ${artifactName}`;
    bodyEl.innerHTML = "<p class='text-muted'>Loading document...</p>";
    modal.classList.add("open");
    backdrop.classList.add("active");

    try {
        const res = await fetch(`/api/artifacts/${currentSessionId}/${artifactName}`);
        const data = await res.json();
        bodyEl.innerHTML = marked.parse(data.content || "");
        bodyEl.querySelectorAll("pre code").forEach((el) => {
            hljs.highlightElement(el);
        });
    } catch (e) {
        bodyEl.innerHTML = `<p class='text-gold'>Gagal memuat artefak: ${e.message}</p>`;
    }
}

function escapeHtml(text) {
    if (!text) return "";
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function scrollToBottom() {
    const stream = document.getElementById("chat-stream");
    stream.scrollTop = stream.scrollHeight;
}
