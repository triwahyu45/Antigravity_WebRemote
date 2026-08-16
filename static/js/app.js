// =========================================================================
// ANTIGRAVITY WEBREMOTE - PRODUCTION CLIENT ENGINE v5.0
// 1:1 Pixel-Perfect Desktop Mirroring, Multi-Mode, PWA & Two-Way Injection
// =========================================================================

const BASE_PATH = window.location.pathname.startsWith('/wahyuai') ? '/wahyuai' : (window.location.pathname.startsWith('/remote') ? '/remote' : '');
let currentSessionId = "63fb64ac-9344-46a1-8d60-a891ba0835d8";
let activeMacro = null;
let activeRightTab = 'plan';
let queuedComments = JSON.parse(localStorage.getItem("ag2r_queued_comments") || "[]");

// --- DOM ELEMENTS ---
const feedContainer = document.getElementById("feed-container");
const chatStream = document.getElementById("chat-stream");
const promptInput = document.getElementById("prompt-input");
const btnSend = document.getElementById("btn-send");
const btnMic = document.getElementById("btn-mic");
const btnPlus = document.getElementById("btn-plus");
const btnModelSelector = document.getElementById("btn-model-selector");
const btnNewConv = document.getElementById("btn-new-conv");
const btnHistory = document.getElementById("btn-history");
const btnScheduled = document.getElementById("btn-scheduled");
const btnSettings = document.getElementById("btn-settings");
const btnProjectsFilter = document.getElementById("btn-projects-filter");
const btnProjectsNew = document.getElementById("btn-projects-new");
const btnOpenIde = document.getElementById("btn-open-ide");
const btnSplitView = document.getElementById("btn-split-view");
const btnToggleLeft = document.getElementById("btn-toggle-left");
const btnCloseRight = document.getElementById("btn-close-right");
const leftSidebar = document.getElementById("left-sidebar");
const rightSidebar = document.getElementById("right-sidebar");

// Modals
const macrosModal = document.getElementById("macros-modal");
const btnCloseMacros = document.getElementById("btn-close-macros");
const settingsModal = document.getElementById("settings-modal");
const btnCloseSettings = document.getElementById("btn-close-settings");
const filterMenu = document.getElementById("projects-filter-menu");
const imageModal = document.getElementById("image-modal");
const imageModalImg = document.getElementById("image-modal-img");
const runningTaskCard = document.getElementById("running-task-card");
const runningTaskDesc = document.getElementById("running-task-desc");
const btnStopTask = document.getElementById("btn-stop-task");

// --- PWA SERVICE WORKER REGISTRATION ---
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js').catch(() => {});
    });
}

// --- ESCAPE HTML UTILITY ---
function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

// --- AUTOSCROLL ENGINE (scrollIntoView) ---
function scrollToBottom(smooth = false) {
    if (!feedContainer || !chatStream) return;
    function doScroll() {
        const lastEl = feedContainer.lastElementChild;
        if (lastEl) {
            lastEl.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'end', inline: 'nearest' });
        }
        chatStream.scrollTop = chatStream.scrollHeight + 999999;
    }
    doScroll();
    requestAnimationFrame(doScroll);
    setTimeout(doScroll, 40);
    setTimeout(doScroll, 120);
    setTimeout(doScroll, 350);
}

// --- WEBSOCKET LIVE STREAMING ---
let ws = null;
let wsReconnectDelay = 1000;

function connectWebSocket() {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${proto}//${window.location.host}/ws/stream`;
    
    try {
        ws = new WebSocket(wsUrl);
        ws.onopen = () => {
            console.log("[WS] Connected to live stream");
            wsReconnectDelay = 1000;
        };
        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.event === "transcript_update") {
                    renderGroupedSteps(data.items);
                    updateEngineState(data.engine_state);
                } else if (data.event === "status_heartbeat") {
                    updateEngineState(data.engine_state);
                }
            } catch (e) {}
        };
        ws.onclose = () => {
            setTimeout(connectWebSocket, wsReconnectDelay);
            wsReconnectDelay = Math.min(wsReconnectDelay * 1.5, 10000);
        };
    } catch (e) {
        setTimeout(connectWebSocket, 3000);
    }
}

// --- ENGINE & TASK STATUS UPDATER ---
function updateEngineState(state) {
    if (!state) return;
    const pill = document.getElementById("engine-status-pill");
    const text = document.getElementById("engine-status-text");
    
    if (state.status === "working") {
        if (pill) { pill.className = "agy-status-pill working"; }
        if (text) { text.textContent = `Working (${state.elapsed_seconds || 0}s)`; }
        if (runningTaskCard) {
            runningTaskCard.style.display = "flex";
            if (runningTaskDesc) runningTaskDesc.textContent = state.current_action || "Executing command...";
        }
    } else {
        if (pill) { pill.className = "agy-status-pill idle"; }
        if (text) { text.textContent = "Idle"; }
        if (runningTaskCard) { runningTaskCard.style.display = "none"; }
    }
}

// --- LOAD PROJECTS TREE ---
async function loadProjectsTree() {
    try {
        const res = await fetch(`${BASE_PATH}/api/projects`);
        const data = await res.json();
        renderProjects(data.projects || []);
        if (data.active_id) currentSessionId = data.active_id;
    } catch (e) {}
}

function renderProjects(projects) {
    const list = document.getElementById("projects-list");
    if (!list) return;
    list.innerHTML = "";

    projects.forEach((proj) => {
        const item = document.createElement("div");
        item.className = "agy-project-item";
        
        let convsHtml = "";
        if (proj.conversations && proj.conversations.length > 0) {
            convsHtml = '<div class="agy-convs-list">';
            proj.conversations.forEach((c) => {
                const activeClass = c.id === currentSessionId ? "active" : "";
                convsHtml += `
                    <div class="agy-conv-item ${activeClass}" onclick="switchConversation('${c.id}', '${escapeHtml(c.title)}')">
                        <span class="conv-title">${escapeHtml(c.title)}</span>
                        <span class="conv-time">${c.time || ""}</span>
                    </div>`;
            });
            convsHtml += "</div>";
        }

        item.innerHTML = `
            <div class="agy-project-header">
                <span class="agy-project-title"><i class="far fa-folder" style="color: var(--text-muted);"></i> ${escapeHtml(proj.name)}</span>
                <div class="agy-project-actions">
                    <button class="btn-sidebar-opt" title="Opsi Proyek" onclick="event.stopPropagation(); alert('Proyek: ${escapeHtml(proj.name)}');"><i class="fas fa-ellipsis-v"></i></button>
                    <button class="btn-sidebar-opt" title="Percakapan Baru" onclick="event.stopPropagation(); startNewConversation();"><i class="fas fa-plus"></i></button>
                </div>
            </div>
            ${convsHtml}
        `;
        list.appendChild(item);
    });
}

function switchConversation(cid, title) {
    currentSessionId = cid;
    const headerConv = document.getElementById("header-conv-name");
    if (headerConv) headerConv.textContent = title;
    loadSessionSteps(cid);
    loadProjectsTree();
    if (window.innerWidth < 768 && leftSidebar) leftSidebar.classList.remove("open");
}

function startNewConversation() {
    const title = prompt("Nama Percakapan Baru:", "Percakapan Baru");
    if (title) {
        alert(`Membuat percakapan baru: ${title}`);
    }
}

// --- LOAD SESSION STEPS & RENDER CHAT ---
async function loadSessionSteps(cid) {
    try {
        const res = await fetch(`${BASE_PATH}/api/sessions/${cid}/steps`);
        const steps = await res.json();
        renderGroupedSteps(steps, true);
    } catch (e) {}
}

function renderGroupedSteps(steps, isInitial = false) {
    if (!feedContainer) return;
    feedContainer.innerHTML = "";

    let currentToolBatch = [];

    function flushToolBatch() {
        if (currentToolBatch.length === 0) return;
        const count = currentToolBatch.length;
        const details = document.createElement("details");
        details.className = "agy-tool-accordion";
        
        let actionsHtml = "";
        currentToolBatch.forEach((tb) => {
            actionsHtml += `<div class="agy-tool-row"><span class="tool-icon">⚡</span> <span class="tool-name">${escapeHtml(tb.name)}:</span> <span class="tool-summary">${escapeHtml(tb.summary || "")}</span></div>`;
        });
        
        details.innerHTML = `
            <summary class="agy-tool-summary">
                <span class="acc-arrow"><i class="fas fa-chevron-right"></i></span>
                <span class="acc-title">Exploring ${count} actions & tool executions</span>
            </summary>
            <div class="agy-tool-details-body">${actionsHtml}</div>
        `;
        feedContainer.appendChild(details);
        currentToolBatch = [];
    }

    steps.forEach((step) => {
        if (step.type === "tool_call") {
            currentToolBatch.push(step);
            return;
        }

        flushToolBatch();

        if (step.type === "user") {
            const card = document.createElement("div");
            card.className = "agy-user-message-card";
            
            let imgsHtml = "";
            if (step.images && step.images.length > 0) {
                imgsHtml = '<div class="user-msg-images">';
                step.images.forEach(img => {
                    imgsHtml += `<img src="${BASE_PATH}/api/uploads/${step.session_id || currentSessionId}/${img}" class="user-img-thumb" onclick="openImageModal(this.src)" title="Klik untuk perbesar" />`;
                });
                imgsHtml += '</div>';
            }
            
            card.innerHTML = `${imgsHtml}<div class="user-msg-text">${escapeHtml(step.text)}</div>`;
            feedContainer.appendChild(card);
        } else if (step.type === "assistant") {
            const row = document.createElement("div");
            row.className = "agy-assistant-message markdown-body";
            
            let htmlContent = marked.parse(step.text || "");
            
            // Inline Artifact Cards
            let artifactCardsHtml = "";
            if (step.text.includes("implementation_plan.md") || step.text.includes("Implementation Plan")) {
                artifactCardsHtml += `<div class="agy-inline-artifact-card" onclick="openArtifactInPanel('implementation_plan.md')"><i class="fas fa-file-alt"></i> Implementation Plan</div>`;
            }
            if (step.text.includes("walkthrough.md") || step.text.includes("Walkthrough")) {
                artifactCardsHtml += `<div class="agy-inline-artifact-card" onclick="openArtifactInPanel('walkthrough.md')"><i class="fas fa-book-open" style="color: #4ade80;"></i> Walkthrough</div>`;
            }

            row.innerHTML = artifactCardsHtml + htmlContent;

            // Highlight Code & Add 1-Tap Copy
            row.querySelectorAll("pre").forEach((pre) => {
                const wrapper = document.createElement("div");
                wrapper.className = "code-block-wrapper";
                pre.parentNode.insertBefore(wrapper, pre);
                wrapper.appendChild(pre);

                const copyBtn = document.createElement("button");
                copyBtn.className = "btn-copy-code";
                copyBtn.innerHTML = '<i class="far fa-copy"></i> Copy';
                copyBtn.addEventListener("mousedown", (e) => e.preventDefault());
                copyBtn.addEventListener("click", () => {
                    const code = pre.querySelector("code") ? pre.querySelector("code").innerText : pre.innerText;
                    navigator.clipboard.writeText(code).then(() => {
                        copyBtn.classList.add("copied");
                        copyBtn.innerHTML = '<i class="fas fa-check"></i> Copied!';
                        if (navigator.vibrate) navigator.vibrate(30);
                        setTimeout(() => {
                            copyBtn.classList.remove("copied");
                            copyBtn.innerHTML = '<i class="far fa-copy"></i> Copy';
                        }, 2000);
                    });
                });
                wrapper.appendChild(copyBtn);
            });

            row.querySelectorAll("pre code").forEach((el) => hljs.highlightElement(el));
            feedContainer.appendChild(row);
        }
    });

    flushToolBatch();
    scrollToBottom(!isInitial);
}

// --- SEND MESSAGE & TWO-WAY INJECTION ---
async function handleSend() {
    if (!promptInput) return;
    let text = promptInput.value.trim();
    if (!text && queuedComments.length === 0) return;

    if (activeMacro) {
        text = `${activeMacro} ${text}`.trim();
        removeActiveMacro();
    }

    if (queuedComments.length > 0) {
        let commentsMd = "\n\n### 💬 Review Comments:\n";
        queuedComments.forEach((c) => {
            commentsMd += `* > "${c.quote.slice(0, 150)}..."\n  * **Comment:** ${c.comment}\n`;
        });
        text = (text + commentsMd).trim();
        queuedComments = [];
        localStorage.setItem("ag2r_queued_comments", "[]");
        renderCommentQueuePill();
    }

    promptInput.value = "";
    if (navigator.vibrate) navigator.vibrate([20, 40, 20]);

    try {
        await fetch(`${BASE_PATH}/api/chat/send`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: text, session_id: currentSessionId })
        });
    } catch (e) {}
}

if (btnSend) btnSend.addEventListener("click", handleSend);

// Mobile vs Desktop Enter Key
const isMobileDevice = window.matchMedia("(pointer: coarse)").matches;
if (promptInput) {
    promptInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            if (!isMobileDevice && !e.shiftKey) {
                e.preventDefault();
                handleSend();
            }
        }
    });
}

// --- ACTION MACROS MODAL LOGIC ---
if (btnPlus && macrosModal) {
    btnPlus.addEventListener("click", () => {
        macrosModal.style.display = "flex";
        if (navigator.vibrate) navigator.vibrate(25);
    });
}
if (btnCloseMacros && macrosModal) {
    btnCloseMacros.addEventListener("click", () => { macrosModal.style.display = "none"; });
    macrosModal.addEventListener("click", (e) => { if (e.target === macrosModal) macrosModal.style.display = "none"; });
}
document.querySelectorAll(".macro-option-item").forEach((item) => {
    item.addEventListener("click", () => {
        const macro = item.getAttribute("data-macro");
        setActiveMacro(macro);
        macrosModal.style.display = "none";
        if (promptInput) promptInput.focus();
        if (navigator.vibrate) navigator.vibrate([20, 30]);
    });
});

function setActiveMacro(macro) {
    activeMacro = macro;
    let existingPill = document.querySelector(".active-macro-pill");
    if (existingPill) existingPill.remove();

    if (macro && promptInput) {
        const pill = document.createElement("span");
        pill.className = "active-macro-pill";
        pill.innerHTML = `${macro} <button type="button" id="btn-remove-macro">&times;</button>`;
        pill.querySelector("button").addEventListener("click", (e) => {
            e.stopPropagation();
            removeActiveMacro();
        });
        promptInput.parentNode.insertBefore(pill, promptInput);
    }
}

function removeActiveMacro() {
    activeMacro = null;
    const pill = document.querySelector(".active-macro-pill");
    if (pill) pill.remove();
}

// --- RIGHT SIDEBAR TABS & ARTIFACT READER ---
function switchRightTab(tab) {
    activeRightTab = tab;
    document.querySelectorAll('.agy-right-tab-item').forEach(el => {
        el.classList.toggle('active', el.getAttribute('data-tab') === tab);
    });
    
    const body = document.getElementById('right-artifact-body');
    if (!body) return;
    
    body.innerHTML = '<div style="text-align: center; padding: 30px; color: var(--text-muted);"><i class="fas fa-spinner fa-spin"></i> Memuat dokumen...</div>';
    
    if (tab === 'plan') {
        fetchArtifactAndRender('implementation_plan.md');
    } else if (tab === 'walkthrough') {
        fetchArtifactAndRender('walkthrough.md');
    } else if (tab === 'diffs') {
        loadDiffsIntoRightPanel();
    }
}

async function fetchArtifactAndRender(filename) {
    const body = document.getElementById('right-artifact-body');
    try {
        const res = await fetch(`${BASE_PATH}/api/artifacts/${currentSessionId}/${filename}`);
        if (!res.ok) {
            body.innerHTML = `<div style="color: var(--text-muted); text-align: center; padding: 40px 10px;">Dokumen <b>${filename}</b> belum tersedia.</div>`;
            return;
        }
        const data = await res.json();
        body.innerHTML = marked.parse(data.content || "");
        body.querySelectorAll("pre code").forEach((el) => hljs.highlightElement(el));
    } catch (e) {
        body.innerHTML = `<div style="color: #f87171; padding: 20px;">Gagal memuat: ${e.message}</div>`;
    }
}

async function loadDiffsIntoRightPanel() {
    const body = document.getElementById('right-artifact-body');
    try {
        const res = await fetch(`${BASE_PATH}/api/review/diff`);
        const data = await res.json();
        if (data.files && data.files.length > 0) {
            let html = "";
            data.files.forEach(f => {
                html += `<div class="diff-file-card">
                    <div class="diff-file-header"><span>📁 ${f.name}</span> <span class="macro-badge">${f.status}</span></div>
                    <div class="diff-lines">`;
                f.lines.forEach(l => {
                    const cls = l.startsWith("+") ? "add" : (l.startsWith("-") ? "del" : "");
                    html += `<div class="diff-line ${cls}">${escapeHtml(l)}</div>`;
                });
                html += `</div></div>`;
            });
            body.innerHTML = html;
        } else {
            body.innerHTML = `<div style="text-align: center; color: var(--text-muted); padding: 30px;">Tidak ada diff perubahan saat ini.</div>`;
        }
    } catch (e) {
        body.innerHTML = `<div style="color: #f87171; padding: 20px;">Gagal memuat diffs: ${e.message}</div>`;
    }
}

function openArtifactInPanel(filename) {
    if (rightSidebar) {
        rightSidebar.classList.add('open');
        if (filename.includes('plan')) switchRightTab('plan');
        else if (filename.includes('walkthrough')) switchRightTab('walkthrough');
        else fetchArtifactAndRender(filename);
    }
}

function toggleRightSidebar() {
    if (rightSidebar) rightSidebar.classList.toggle("open");
}

if (btnSplitView) btnSplitView.addEventListener("click", toggleRightSidebar);
if (btnToggleLeft && leftSidebar) btnToggleLeft.addEventListener("click", () => leftSidebar.classList.toggle("open"));

// --- PROJECTS FILTER CONTEXT MENU ---
if (btnProjectsFilter && filterMenu) {
    btnProjectsFilter.addEventListener("click", (e) => {
        e.stopPropagation();
        const rect = btnProjectsFilter.getBoundingClientRect();
        filterMenu.style.top = `${rect.bottom + 6}px`;
        filterMenu.style.left = `${rect.left}px`;
        filterMenu.style.display = filterMenu.style.display === "none" ? "block" : "none";
        if (navigator.vibrate) navigator.vibrate(20);
    });
}

document.addEventListener("click", (e) => {
    if (filterMenu && !filterMenu.contains(e.target) && e.target !== btnProjectsFilter) {
        filterMenu.style.display = "none";
    }
});

document.querySelectorAll(".ctx-item").forEach(item => {
    item.addEventListener("click", () => {
        const action = item.getAttribute("data-action");
        if (action) {
            document.querySelectorAll(".ctx-item").forEach(other => {
                if (other.getAttribute("data-action")?.split("-")[0] === action.split("-")[0]) {
                    other.classList.remove("active");
                    other.querySelector(".ctx-check").textContent = "";
                }
            });
            item.classList.add("active");
            item.querySelector(".ctx-check").textContent = "✓";
            filterMenu.style.display = "none";
        }
    });
});

// --- SETTINGS & BUTTON TRIGGERS ---
if (btnSettings && settingsModal) {
    btnSettings.addEventListener("click", () => {
        settingsModal.style.display = "flex";
        if (navigator.vibrate) navigator.vibrate(20);
    });
}
if (btnCloseSettings && settingsModal) {
    btnCloseSettings.addEventListener("click", () => { settingsModal.style.display = "none"; });
    settingsModal.addEventListener("click", (e) => { if (e.target === settingsModal) settingsModal.style.display = "none"; });
}
if (btnNewConv) btnNewConv.addEventListener("click", startNewConversation);
if (btnProjectsNew) btnProjectsNew.addEventListener("click", () => { prompt("Nama Folder Proyek Baru:"); });
if (btnHistory) btnHistory.addEventListener("click", () => { alert("Riwayat Percakapan Aktif."); });
if (btnScheduled) btnScheduled.addEventListener("click", () => { alert("Scheduled Tasks: Tidak ada task cron aktif."); });
if (btnOpenIde) btnOpenIde.addEventListener("click", () => { alert("Antigravity IDE Aktif."); });
if (btnModelSelector) btnModelSelector.addEventListener("click", () => { alert("Model: Gemini 3.7 Flash Medium"); });

// --- IMAGE LIGHTBOX MODAL ---
function openImageModal(src) {
    if (imageModal && imageModalImg) {
        imageModalImg.src = src;
        imageModal.style.display = "flex";
        if (navigator.vibrate) navigator.vibrate(20);
    }
}

// --- COMMENT QUEUING SELECTION FAB ---
function renderCommentQueuePill() {
    let pill = document.getElementById("comment-queue-indicator");
    if (queuedComments.length === 0) {
        if (pill) pill.remove();
        return;
    }
    if (!pill) {
        pill = document.createElement("div");
        pill.id = "comment-queue-indicator";
        pill.className = "comment-queue-pill";
        const inputArea = document.querySelector(".agy-input-capsule");
        if (inputArea) inputArea.parentNode.insertBefore(pill, inputArea);
    }
    pill.innerHTML = `💬 ${queuedComments.length} comment(s) queued <button type="button" id="btn-clear-comments">&times;</button>`;
    pill.querySelector("#btn-clear-comments").addEventListener("click", (e) => {
        e.stopPropagation();
        queuedComments = [];
        localStorage.setItem("ag2r_queued_comments", "[]");
        renderCommentQueuePill();
    });
}

// --- VOICE RECOGNITION (MIC) ---
if (btnMic) {
    btnMic.addEventListener("click", () => {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            alert("Browser tidak mendukung Speech Recognition.");
            return;
        }
        const rec = new SpeechRecognition();
        rec.lang = "id-ID";
        btnMic.style.color = "var(--emerald-neon)";
        rec.onresult = (e) => {
            const transcript = e.results[0][0].transcript;
            if (promptInput) promptInput.value += (promptInput.value ? " " : "") + transcript;
            btnMic.style.color = "";
        };
        rec.onerror = () => { btnMic.style.color = ""; };
        rec.onend = () => { btnMic.style.color = ""; };
        rec.start();
    });
}

// --- INITIALIZE ON LOAD ---
document.addEventListener("DOMContentLoaded", () => {
    loadProjectsTree();
    loadSessionSteps(currentSessionId);
    connectWebSocket();
    renderCommentQueuePill();
    switchRightTab("plan");
});