// ==========================================================================
// ULTIMATE ANTIGRAVITY CONTROLLER WITH ACCORDIONS & ZERO OVERSCROLL
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

        appendUserMessage(text);
        promptInput.value = "";
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

// WEBSOCKET REAL-TIME SYNC
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
                renderGroupedSteps(data.items);
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
    const tasksCard = document.getElementById("floating-tasks-card");
    const tasksLabel = document.getElementById("tasks-count-label");
    const taskCmd = document.getElementById("task-active-cmd");
    const btnSend = document.getElementById("btn-send");

    if (state.status === "working") {
        badge.className = "status-indicator-badge working";
        text.textContent = "Working";
        
        if (tasksCard) {
            tasksCard.classList.remove("hidden");
            taskCmd.textContent = state.current_action || "Thinking...";
        }
        
        if (btnSend) {
            btnSend.classList.add("stop-state");
            btnSend.innerHTML = '<i class="fas fa-square"></i>';
            btnSend.title = "Stop Generation";
        }
    } else {
        badge.className = "status-indicator-badge idle";
        text.textContent = "Idle";
        
        if (tasksCard) {
            tasksCard.classList.add("hidden");
        }
        
        if (btnSend) {
            btnSend.classList.remove("stop-state");
            btnSend.innerHTML = '<i class="fas fa-arrow-up"></i>';
            btnSend.title = "Send message";
        }
    }
}

// LOAD PROJECTS TREE
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
                item.innerHTML = `<span class="conv-name">${conv.title}</span> <span class="time-badge">${conv.time}</span>`;
                
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

// LOAD STEPS
let renderedCount = 0;

async function loadSessionSteps(sessionId) {
    try {
        const res = await fetch(`/api/sessions/${sessionId}/steps`);
        const steps = await res.json();
        renderGroupedSteps(steps, true);
    } catch (e) {
        console.error("Steps error:", e);
    }
}

// RENDER GROUPED STEPS (ACCORDION STYLE 1:1 WITH ANTIGRAVITY SCREENSHOT!)
function renderGroupedSteps(steps, forceScroll = false) {
    const container = document.getElementById("feed-container");
    if (steps.length === renderedCount && !forceScroll) return;

    container.innerHTML = "";
    renderedCount = steps.length;

    let currentActivities = [];

    function flushActivities() {
        if (currentActivities.length === 0) return;

        const row = document.createElement("div");
        row.className = "feed-row activity_group";

        // Count files & folders
        let fileCount = 0;
        let folderCount = 0;
        currentActivities.forEach(act => {
            if (act.name === "view_file" || act.name === "write_to_file" || act.name === "replace_file_content") fileCount++;
            else if (act.name === "list_dir" || act.name === "find_by_name") folderCount++;
        });

        let headerText = "Thinking & Exploring";
        if (fileCount > 0 && folderCount > 0) {
            headerText = `Exploring ${fileCount} file${fileCount > 1 ? 's' : ''}, ${folderCount} folder${folderCount > 1 ? 's' : ''}`;
        } else if (fileCount > 0) {
            headerText = `Exploring ${fileCount} file${fileCount > 1 ? 's' : ''}`;
        } else if (folderCount > 0) {
            headerText = `Exploring ${folderCount} folder${folderCount > 1 ? 's' : ''}`;
        } else {
            headerText = `Worked for ${currentActivities.length * 2}s`;
        }

        const headerEl = document.createElement("div");
        headerEl.className = "activity-header";
        headerEl.innerHTML = `<span>${headerText}</span> <i class="fas fa-chevron-down"></i>`;

        const bodyEl = document.createElement("div");
        bodyEl.className = "activity-body collapsed";

        currentActivities.forEach(act => {
            const line = document.createElement("div");
            line.className = "activity-line";

            if (act.name === "view_file") {
                const target = act.summary.replace("View ", "").replace("View file ", "");
                line.innerHTML = `<span class="keyword">Analyzed</span> <span class="tag">{ }</span> <span class="target-path">${escapeHtml(target)}</span>`;
            } else if (act.name === "list_dir" || act.name === "find_by_name") {
                const target = act.summary.replace("List ", "").replace("Search ", "");
                line.innerHTML = `<span class="keyword">Analyzed</span> <span class="tag">📁</span> <span class="target-path">${escapeHtml(target)}</span>`;
            } else if (act.name === "run_command") {
                line.innerHTML = `<span class="keyword">Ran</span> <span class="tag">⚡</span> <span class="target-path">${escapeHtml(act.summary)}</span>`;
            } else if (act.name === "write_to_file" || act.name === "replace_file_content") {
                line.innerHTML = `<span class="keyword">Modified</span> <span class="tag">📝</span> <span class="target-path">${escapeHtml(act.summary)}</span>`;
            } else {
                line.innerHTML = `<span class="keyword">Executed</span> <span class="tag">⚡</span> <span class="target-path">${escapeHtml(act.name)}: ${escapeHtml(act.summary)}</span>`;
            }

            bodyEl.appendChild(line);
        });

        headerEl.addEventListener("click", () => {
            const isCollapsed = bodyEl.classList.toggle("collapsed");
            headerEl.classList.toggle("open", !isCollapsed);
        });

        row.appendChild(headerEl);
        row.appendChild(bodyEl);
        container.appendChild(row);

        currentActivities = [];
    }

    steps.forEach((step, idx) => {
        if (step.type === "user") {
            flushActivities();
            const row = document.createElement("div");
            row.className = "feed-row user";
            let imgHtml = "";
            if (step.images && step.images.length > 0) {
                imgHtml = '<div class="user-uploaded-grid">';
                step.images.forEach(img => {
                    const sid = step.session_id || currentSessionId;
                    imgHtml += `<img src="/api/uploads/${sid}/${img}" class="user-img-thumb" onclick="openImageModal('/api/uploads/${sid}/${img}')" />`;
                });
                imgHtml += '</div>';
            }
            row.innerHTML = `<div class="user-bubble">${imgHtml}${escapeHtml(step.text)}</div>`;
            container.appendChild(row);
        } else if (step.type === "tool_call") {
            currentActivities.push(step);
        } else if (step.type === "assistant") {
            flushActivities();
            const row = document.createElement("div");
            row.className = "feed-row assistant";

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
            container.appendChild(row);
        }
    });

    // If active tools are still going at the bottom
    if (currentActivities.length > 0) {
        flushActivities();
    }

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

function openImageModal(imgSrc) {
    const modal = document.getElementById("artifact-modal");
    const backdrop = document.getElementById("backdrop-modal");
    const titleEl = document.getElementById("modal-art-title");
    const bodyEl = document.getElementById("modal-art-body");

    titleEl.innerHTML = `<i class="far fa-image text-cyan"></i> Image Preview`;
    bodyEl.innerHTML = `<div style="display:flex;justify-content:center;"><img src="${imgSrc}" style="max-width:100%;max-height:70vh;border-radius:8px;" /></div>`;
    modal.classList.add("open");
    backdrop.classList.add("active");
}
