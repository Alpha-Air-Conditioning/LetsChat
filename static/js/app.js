const messageInput = document.getElementById('messageInput');
const sendButton = document.getElementById('sendButton');
const messagesContainer = document.getElementById('messages');

const conversationId = window.CHAT_CONFIG?.conversationId || '';
const currentUsername = window.CHAT_CONFIG?.currentUsername || '';
const currentUserId = window.CHAT_CONFIG?.currentUserId || '';

const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
const socketUrl = conversationId
    ? `${protocol}://${window.location.host}/ws/chat/${conversationId}/`
    : `${protocol}://${window.location.host}/ws/user/`;

let socket = null;
let reconnectTimer = null;
let pingInterval = null;
const pendingSocketQueue = [];

function connectWebSocket() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
        return;
    }

    try {
        socket = new WebSocket(socketUrl);
    } catch (e) {
        console.error('[LetsChat] WebSocket init error:', e);
        scheduleReconnect();
        return;
    }

    socket.onopen = function () {
        console.log('[LetsChat] Connected to channel:', conversationId);
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }

        // Keepalive heartbeat every 15s to prevent tunnel / mobile sleep timeouts
        if (pingInterval) clearInterval(pingInterval);
        pingInterval = setInterval(() => {
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ action: 'ping' }));
            }
        }, 15000);

        // Flush any buffered signaling messages
        while (pendingSocketQueue.length > 0) {
            const item = pendingSocketQueue.shift();
            try {
                socket.send(JSON.stringify(item));
            } catch (err) {
                console.warn('[LetsChat] Failed sending queued item:', err);
            }
        }
    };

    socket.onclose = function (e) {
        console.warn('[LetsChat] Disconnected (code: ' + e.code + '). Reconnecting...');
        if (pingInterval) {
            clearInterval(pingInterval);
            pingInterval = null;
        }
        scheduleReconnect();
    };

    socket.onerror = function (error) {
        console.error('[LetsChat] Socket Error:', error);
        try { socket.close(); } catch (e) {}
    };

    socket.onmessage = function (event) {
        try {
            const data = JSON.parse(event.data);
            if (data.action === 'pong') {
                return; // Heartbeat response
            }
            if (data.error) {
                alert(data.error);
                return;
            }
            if (data.action === 'delete') {
                const el = document.getElementById('msg-' + data.message_id);
                if (el) {
                    el.style.transition = 'opacity 0.2s ease, transform 0.2s ease';
                    el.style.opacity = '0';
                    el.style.transform = 'scale(0.95)';
                    setTimeout(() => {
                        el.remove();
                        updateHeaderMessageCount();
                    }, 200);
                }
                return;
            }
            if (data.action === 'presence_update') {
                const statusEl = document.getElementById('chatHeaderStatus');
                if (statusEl && statusEl.getAttribute('data-other-user-id') === String(data.user_id)) {
                    const dotEl = document.getElementById('chatHeaderStatusDot');
                    const textEl = document.getElementById('chatHeaderStatusText');
                    if (data.is_online) {
                        statusEl.className = 'text-[11px] flex items-center gap-1.5 truncate text-emerald-400';
                        if (dotEl) dotEl.className = 'w-1.5 h-1.5 rounded-full shrink-0 bg-emerald-500 animate-pulse';
                        if (textEl) textEl.textContent = 'online';
                    } else {
                        statusEl.className = 'text-[11px] flex items-center gap-1.5 truncate text-zinc-500';
                        if (dotEl) dotEl.className = 'w-1.5 h-1.5 rounded-full shrink-0 bg-zinc-600';
                        if (textEl) textEl.textContent = data.last_seen || 'offline';
                    }
                }
                return;
            }
            if (['call_offer', 'call_answer', 'ice_candidate', 'call_reject', 'call_end', 'call_busy'].includes(data.action)) {
                handleCallSignal(data);
                return;
            }
            addMessage(data);
        } catch (e) {
            console.error('Failed to parse WebSocket message:', e);
        }
    };
}

function scheduleReconnect() {
    if (!reconnectTimer) {
        reconnectTimer = setTimeout(() => {
            reconnectTimer = null;
            connectWebSocket();
        }, 1500);
    }
}

// Reconnect immediately on mobile wakeup or network change
window.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
        if (!socket || socket.readyState === WebSocket.CLOSED || socket.readyState === WebSocket.CLOSING) {
            connectWebSocket();
        }
    }
});
window.addEventListener('online', connectWebSocket);

// Initialize connection
connectWebSocket();

function deleteMessage(messageId) {
    if (!confirm('Are you sure you want to delete this message?')) return;

    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
            action: 'delete_message',
            message_id: messageId
        }));
    } else {
        fetch(`/delete-message/${messageId}/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCookie('csrftoken') || '',
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success') {
                const el = document.getElementById('msg-' + messageId);
                if (el) el.remove();
            }
        })
        .catch(err => console.error('Failed to delete message:', err));
    }
}

function scrollToBottom(smooth = false) {
    if (!messagesContainer) return;
    requestAnimationFrame(() => {
        try {
            if (smooth) {
                messagesContainer.scrollTo({
                    top: messagesContainer.scrollHeight,
                    behavior: 'smooth'
                });
            } else {
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
            }
        } catch (e) {
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }

        // Additional fallback: scroll the last message into view
        const lastMsg = messagesContainer.lastElementChild;
        if (lastMsg && typeof lastMsg.scrollIntoView === 'function') {
            lastMsg.scrollIntoView({ block: 'end', behavior: smooth ? 'smooth' : 'auto' });
        }
    });
}

function sendMessage() {
    if (!messageInput) return;
    const message = messageInput.value.trim();

    if (!message) return;

    if (socket.readyState !== WebSocket.OPEN) {
        alert('Chat connection is reconnecting. Please retry in a moment.');
        return;
    }

    socket.send(JSON.stringify({
        message: message
    }));

    messageInput.value = '';
    messageInput.focus();
    scrollToBottom(true);
}

function copyMessageContent(btn) {
    if (!btn) return;
    const row = btn.closest('.group\\/msg');
    if (!row) return;
    const textEl = row.querySelector('.msg-text');
    if (textEl) {
        const text = textEl.innerText.trim();
        if (text) {
            if (window.copyTextToClipboard) {
                window.copyTextToClipboard(text, 'Message copied to clipboard');
            } else if (navigator.clipboard) {
                navigator.clipboard.writeText(text).catch(() => {});
            }
            const svg = btn.querySelector('svg');
            if (svg) {
                const orig = svg.outerHTML;
                btn.innerHTML = `<svg class="w-3.5 h-3.5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>`;
                setTimeout(() => { btn.innerHTML = orig; }, 1500);
            }
        }
    }
}
window.copyMessageContent = copyMessageContent;

function addMessage(data) {
    if (!messagesContainer) return;

    const emptyChat = document.getElementById('emptyChat');
    if (emptyChat) {
        emptyChat.remove();
    }

    const isOutgoing = data.sender === currentUsername;

    const row = document.createElement('div');
    if (data.id) {
        row.id = 'msg-' + data.id;
    }
    row.className = `flex ${isOutgoing ? 'justify-end' : 'justify-start'} group/msg`;

    const container = document.createElement('div');

    if (isOutgoing) {
        container.className = 'relative group/bubble flex items-end gap-1.5 max-w-[85%] sm:max-w-[70%]';

        // Action buttons container (Copy & Delete)
        const actionsContainer = document.createElement('div');
        actionsContainer.className = 'flex items-center gap-0.5 opacity-0 group-hover/msg:opacity-100 transition-opacity mb-0.5 shrink-0';

        // Copy button for text messages
        if (!data.audio_url) {
            const copyBtn = document.createElement('button');
            copyBtn.type = 'button';
            copyBtn.title = 'Copy Message';
            copyBtn.className = 'p-1 text-zinc-500 hover:text-blue-400 rounded-lg hover:bg-zinc-800/80 active:scale-95 transition-all';
            copyBtn.onclick = function() { copyMessageContent(copyBtn); };
            copyBtn.innerHTML = `
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path>
                </svg>
            `;
            actionsContainer.appendChild(copyBtn);
        }

        // Delete button for outgoing messages
        if (data.id) {
            const delBtn = document.createElement('button');
            delBtn.type = 'button';
            delBtn.title = 'Delete Message';
            delBtn.className = 'p-1 text-zinc-500 hover:text-rose-400 rounded-lg hover:bg-zinc-800/80 active:scale-95 transition-all';
            delBtn.onclick = function() { deleteMessage(data.id); };
            delBtn.innerHTML = `
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                </svg>
            `;
            actionsContainer.appendChild(delBtn);
        }

        container.appendChild(actionsContainer);

        // Outgoing bubble
        const bubble = document.createElement('div');
        bubble.className = 'bg-blue-600 text-white rounded-2xl rounded-br-sm px-3.5 py-2 text-sm shadow-sm flex flex-col items-start w-fit min-w-[65px]';

        if (data.audio_url) {
            const waveEl = createAudioWaveElement(data.audio_url, true);
            bubble.appendChild(waveEl);
        } else {
            const content = document.createElement('div');
            content.className = 'msg-text break-words leading-relaxed whitespace-pre-wrap text-left';
            content.style.overflowWrap = 'anywhere';
            content.style.wordBreak = 'break-word';
            content.textContent = data.message;
            bubble.appendChild(content);
        }

        const time = document.createElement('div');
        time.className = 'text-[10px] font-mono text-blue-200/80 self-end mt-0.5 -mb-0.5 -mr-0.5';
        const date = new Date(data.created_at || Date.now());
        time.textContent = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        bubble.appendChild(time);

        container.appendChild(bubble);
    } else {
        container.className = 'flex items-end gap-1.5 max-w-[85%] sm:max-w-[70%]';

        // Avatar
        const avatar = document.createElement('div');
        avatar.className = 'w-7 h-7 rounded-lg shrink-0 flex items-center justify-center text-[11px] font-semibold overflow-hidden bg-zinc-800 text-zinc-200 border border-zinc-700/60 mb-0.5';
        if (data.sender_avatar) {
            const img = document.createElement('img');
            img.src = data.sender_avatar;
            img.alt = data.sender || '';
            img.className = 'w-full h-full object-cover';
            img.onload = () => scrollToBottom(false);
            avatar.appendChild(img);
        } else {
            avatar.textContent = (data.sender || '?').charAt(0).toUpperCase();
        }
        container.appendChild(avatar);

        // Incoming bubble
        const bubble = document.createElement('div');
        bubble.className = 'bg-[#18181b] border border-zinc-800 text-zinc-100 rounded-2xl rounded-bl-sm px-3.5 py-2 text-sm shadow-sm flex flex-col items-start w-fit min-w-[60px]';

        if (data.audio_url) {
            const waveEl = createAudioWaveElement(data.audio_url, false);
            bubble.appendChild(waveEl);
        } else {
            const content = document.createElement('div');
            content.className = 'msg-text break-words leading-relaxed whitespace-pre-wrap text-left';
            content.style.overflowWrap = 'anywhere';
            content.style.wordBreak = 'break-word';
            content.textContent = data.message;
            bubble.appendChild(content);
        }

        const time = document.createElement('div');
        time.className = 'text-[10px] font-mono text-zinc-500 self-end mt-0.5 -mb-0.5 -mr-0.5 whitespace-nowrap';
        const date = new Date(data.created_at || Date.now());
        time.textContent = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        bubble.appendChild(time);

        container.appendChild(bubble);

        // Copy button for incoming text messages
        if (!data.audio_url) {
            const copyBtn = document.createElement('button');
            copyBtn.type = 'button';
            copyBtn.title = 'Copy Message';
            copyBtn.className = 'opacity-0 group-hover/msg:opacity-100 transition-opacity p-1 text-zinc-500 hover:text-blue-400 rounded-lg hover:bg-zinc-800/80 mb-0.5 shrink-0 active:scale-95';
            copyBtn.onclick = function() { copyMessageContent(copyBtn); };
            copyBtn.innerHTML = `
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path>
                </svg>
            `;
            container.appendChild(copyBtn);
        }
    }

    row.appendChild(container);
    messagesContainer.appendChild(row);
    scrollToBottom(true);
    updateHeaderMessageCount();
}

function updateHeaderMessageCount() {
    const counterEl = document.getElementById('chatHeaderMsgCount');
    if (counterEl) {
        const count = document.querySelectorAll('#messages > div[id^="msg-"]').length;
        counterEl.textContent = `${count} msgs`;
    }
}

// ----------------------------------------------------
// Custom Audio Wave Player Engine
// ----------------------------------------------------
let currentlyPlayingAudio = null;

function formatAudioTime(seconds) {
    if (isNaN(seconds) || seconds === Infinity) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs < 10 ? '0' : ''}${secs}`;
}

function generateDeterministicWavePattern(src, count = 28) {
    let hash = 0;
    for (let i = 0; i < src.length; i++) {
        hash = (hash << 5) - hash + src.charCodeAt(i);
        hash |= 0;
    }
    const heights = [];
    for (let i = 0; i < count; i++) {
        const pseudo = Math.abs(Math.sin(hash + i * 1.618));
        const h = Math.round(22 + pseudo * 78);
        heights.push(h);
    }
    return heights;
}

function initCustomAudioPlayer(player) {
    if (!player || player.dataset.initialized === 'true') return;
    player.dataset.initialized = 'true';

    const audio = player.querySelector('audio');
    const playBtn = player.querySelector('.play-btn');
    const playIcon = player.querySelector('.play-icon');
    const pauseIcon = player.querySelector('.pause-icon');
    const waveform = player.querySelector('.waveform-container');
    const currTimeEl = player.querySelector('.curr-time');
    const totalTimeEl = player.querySelector('.total-time');
    const isOutgoing = player.dataset.theme === 'outgoing';

    if (!audio || !playBtn || !waveform) return;

    const audioSrc = player.dataset.audioSrc || audio.src || 'default_audio';
    const waveHeights = generateDeterministicWavePattern(audioSrc, 28);

    waveform.innerHTML = '';
    const bars = [];
    waveHeights.forEach((h) => {
        const bar = document.createElement('div');
        bar.className = 'wave-bar w-[3px] rounded-full transition-colors duration-100 flex-shrink-0';
        bar.style.height = `${h}%`;
        bar.style.backgroundColor = isOutgoing ? 'rgba(255, 255, 255, 0.35)' : 'rgb(82, 82, 91)';
        waveform.appendChild(bar);
        bars.push(bar);
    });

    function updateWaveColors(progressRatio) {
        bars.forEach((bar, idx) => {
            const barRatio = idx / bars.length;
            if (barRatio <= progressRatio) {
                bar.style.backgroundColor = isOutgoing ? '#ffffff' : '#3b82f6';
            } else {
                bar.style.backgroundColor = isOutgoing ? 'rgba(255, 255, 255, 0.35)' : 'rgb(82, 82, 91)';
            }
        });
    }

    function setPlayingState(isPlaying) {
        if (isPlaying) {
            playIcon.classList.add('hidden');
            pauseIcon.classList.remove('hidden');
        } else {
            pauseIcon.classList.add('hidden');
            playIcon.classList.remove('hidden');
        }
    }

    playBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (audio.paused) {
            if (currentlyPlayingAudio && currentlyPlayingAudio !== audio) {
                currentlyPlayingAudio.pause();
            }
            audio.play().then(() => {
                currentlyPlayingAudio = audio;
                setPlayingState(true);
            }).catch(err => {
                console.error('Audio play error:', err);
            });
        } else {
            audio.pause();
            setPlayingState(false);
        }
    });

    audio.addEventListener('loadedmetadata', () => {
        if (totalTimeEl && !isNaN(audio.duration) && audio.duration !== Infinity) {
            totalTimeEl.textContent = formatAudioTime(audio.duration);
        }
    });

    audio.addEventListener('timeupdate', () => {
        if (currTimeEl) {
            currTimeEl.textContent = formatAudioTime(audio.currentTime);
        }
        if (totalTimeEl && (totalTimeEl.textContent === '--:--' || totalTimeEl.textContent === '0:00') && !isNaN(audio.duration)) {
            totalTimeEl.textContent = formatAudioTime(audio.duration);
        }
        const progress = audio.duration ? (audio.currentTime / audio.duration) : 0;
        updateWaveColors(progress);
    });

    audio.addEventListener('play', () => {
        setPlayingState(true);
    });

    audio.addEventListener('pause', () => {
        setPlayingState(false);
    });

    audio.addEventListener('ended', () => {
        setPlayingState(false);
        updateWaveColors(0);
        if (currTimeEl) currTimeEl.textContent = '0:00';
    });

    // Seek by clicking or tapping on waveform
    waveform.addEventListener('click', (e) => {
        e.stopPropagation();
        const rect = waveform.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        const ratio = Math.max(0, Math.min(1, clickX / rect.width));
        if (audio.duration && !isNaN(audio.duration)) {
            audio.currentTime = ratio * audio.duration;
            updateWaveColors(ratio);
        }
    });
}

function createAudioWaveElement(audioUrl, isOutgoing) {
    const player = document.createElement('div');
    player.className = 'custom-audio-player flex items-center gap-3 py-1 w-56 sm:w-64';
    player.dataset.audioSrc = audioUrl;
    player.dataset.theme = isOutgoing ? 'outgoing' : 'incoming';

    player.innerHTML = `
        <button type="button" class="play-btn w-9 h-9 rounded-full ${isOutgoing ? 'bg-white text-blue-600' : 'bg-blue-600 text-white hover:bg-blue-500'} flex items-center justify-center shrink-0 shadow-sm hover:scale-105 active:scale-95 transition-all">
            <svg class="play-icon w-4 h-4 ml-0.5 fill-current" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
            <svg class="pause-icon w-4 h-4 fill-current hidden" viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
        </button>
        <div class="flex-1 flex flex-col gap-1 min-w-0">
            <div class="waveform-container flex items-center gap-[2.5px] h-6 cursor-pointer py-1 select-none"></div>
            <div class="flex items-center justify-between text-[10px] font-mono ${isOutgoing ? 'text-blue-100/80' : 'text-zinc-400'} leading-none">
                <span class="curr-time">0:00</span>
                <span class="total-time">--:--</span>
            </div>
        </div>
        <audio src="${audioUrl}" preload="metadata" class="hidden"></audio>
    `;

    initCustomAudioPlayer(player);
    return player;
}

// ----------------------------------------------------
// Cross-Browser Media & UserMedia Helper for Mobile
// ----------------------------------------------------
function showMediaPermissionHelp(reason = 'insecure') {
    const modal = document.getElementById('mediaPermissionModal');
    if (!modal) return;

    const hostEl = document.getElementById('insecureOriginHost');
    if (hostEl) {
        hostEl.textContent = `${window.location.protocol}//${window.location.host}`;
    }

    const titleEl = document.getElementById('mediaPermissionTitle');
    const subEl = document.getElementById('mediaPermissionSubtitle');

    if (reason === 'denied') {
        if (titleEl) titleEl.textContent = 'Microphone Permission Blocked';
        if (subEl) subEl.textContent = 'Please enable microphone access in your browser settings';
    } else {
        if (titleEl) titleEl.textContent = 'Mobile Permission Notice (HTTPS Required)';
        if (subEl) subEl.textContent = 'Mobile browsers block mic/camera access over plain HTTP network addresses';
    }

    modal.classList.remove('hidden');
    modal.classList.add('flex');
}

function closeMediaPermissionModal() {
    const modal = document.getElementById('mediaPermissionModal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
}

async function getCrossBrowserUserMedia(constraints) {
    const isLocalhost = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
    const isSecure = window.isSecureContext || location.protocol === 'https:' || isLocalhost;

    if (!isSecure && !navigator.mediaDevices?.getUserMedia) {
        showMediaPermissionHelp('insecure');
        return Promise.reject(new Error('Mobile browsers require HTTPS or Chrome flag to use microphone/camera.'));
    }

    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        try {
            return await navigator.mediaDevices.getUserMedia(constraints);
        } catch (err) {
            if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
                showMediaPermissionHelp('denied');
            }
            throw err;
        }
    }

    const legacyGetUserMedia = navigator.getUserMedia ||
                               navigator.webkitGetUserMedia ||
                               navigator.mozGetUserMedia ||
                               navigator.msGetUserMedia;
    if (legacyGetUserMedia) {
        return new Promise((resolve, reject) => {
            legacyGetUserMedia.call(navigator, constraints, resolve, (err) => {
                if (err && (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError')) {
                    showMediaPermissionHelp('denied');
                }
                reject(err);
            });
        });
    }

    showMediaPermissionHelp('insecure');
    return Promise.reject(new Error('Media recording is not supported on this browser or origin.'));
}

function getSupportedAudioMimeType() {
    const candidateTypes = [
        'audio/webm;codecs=opus',
        'audio/webm',
        'audio/mp4',
        'audio/aac',
        'audio/ogg;codecs=opus',
        'audio/ogg',
        'audio/wav'
    ];
    for (const t of candidateTypes) {
        if (window.MediaRecorder && typeof MediaRecorder.isTypeSupported === 'function' && MediaRecorder.isTypeSupported(t)) {
            return t;
        }
    }
    return '';
}

// ----------------------------------------------------
// Voice Recording System (MediaRecorder)
// ----------------------------------------------------
let mediaRecorder = null;
let activeAudioStream = null;
let audioChunks = [];
let recordingTimerInterval = null;
let recordingSeconds = 0;
let activeRecordingMimeType = '';

function toggleVoiceRecording() {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        stopAndSendVoiceRecording();
    } else {
        startVoiceRecording();
    }
}

async function startVoiceRecording() {
    try {
        activeAudioStream = await getCrossBrowserUserMedia({ audio: true });
        audioChunks = [];
        activeRecordingMimeType = getSupportedAudioMimeType();

        const recorderOptions = activeRecordingMimeType ? { mimeType: activeRecordingMimeType } : {};
        try {
            mediaRecorder = new MediaRecorder(activeAudioStream, recorderOptions);
        } catch (e) {
            console.warn('Fallback to default MediaRecorder without options:', e);
            mediaRecorder = new MediaRecorder(activeAudioStream);
            activeRecordingMimeType = mediaRecorder.mimeType || '';
        }

        mediaRecorder.ondataavailable = function (e) {
            if (e.data && e.data.size > 0) {
                audioChunks.push(e.data);
            }
        };

        // Collect chunks in smaller slices (e.g. every 200ms)
        mediaRecorder.start(200);

        const textContainer = document.getElementById('textInputContainer');
        const voiceContainer = document.getElementById('voiceRecordingContainer');
        if (textContainer && voiceContainer) {
            textContainer.classList.add('hidden');
            voiceContainer.classList.remove('hidden');
            voiceContainer.classList.add('flex');
        }

        recordingSeconds = 0;
        const timerEl = document.getElementById('recordingTimer');
        if (timerEl) timerEl.textContent = '0:00';
        clearInterval(recordingTimerInterval);
        recordingTimerInterval = setInterval(() => {
            recordingSeconds++;
            const mins = Math.floor(recordingSeconds / 60);
            const secs = recordingSeconds % 60;
            if (timerEl) {
                timerEl.textContent = `${mins}:${secs < 10 ? '0' : ''}${secs}`;
            }
        }, 1000);

    } catch (err) {
        console.error('Microphone access denied or not supported:', err);
        showMediaPermissionHelp(err.name === 'NotAllowedError' ? 'denied' : 'insecure');
    }
}

function cancelVoiceRecording() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.ondataavailable = null;
        mediaRecorder.onstop = null;
        try { mediaRecorder.stop(); } catch (e) {}
    }
    if (activeAudioStream) {
        activeAudioStream.getTracks().forEach(track => track.stop());
        activeAudioStream = null;
    }
    resetRecordingUI();
}

function stopAndSendVoiceRecording() {
    if (!mediaRecorder || mediaRecorder.state === 'inactive') return;

    // Flush any pending data from the recorder
    try {
        if (mediaRecorder.state === 'recording') {
            mediaRecorder.requestData();
        }
    } catch (e) {
        console.warn('MediaRecorder requestData:', e);
    }

    mediaRecorder.onstop = function () {
        if (activeAudioStream) {
            activeAudioStream.getTracks().forEach(track => track.stop());
            activeAudioStream = null;
        }

        const mime = activeRecordingMimeType || (mediaRecorder && mediaRecorder.mimeType) || 'audio/webm';
        const audioBlob = new Blob(audioChunks, { type: mime });

        if (!audioBlob || audioBlob.size === 0) {
            console.warn('Recorded audio is empty.');
            resetRecordingUI();
            return;
        }

        let ext = 'webm';
        if (mime.includes('mp4') || mime.includes('m4a')) ext = 'mp4';
        else if (mime.includes('aac')) ext = 'aac';
        else if (mime.includes('ogg')) ext = 'ogg';
        else if (mime.includes('wav')) ext = 'wav';

        const formData = new FormData();
        formData.append('audio', audioBlob, `voice_${Date.now()}.${ext}`);

        const csrfToken = window.CHAT_CONFIG?.csrfToken || getCookie('csrftoken') || '';

        fetch(`/upload-voice/${conversationId}/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': csrfToken
            },
            body: formData
        })
        .then(async (res) => {
            const data = await res.json().catch(() => ({}));
            if (!res.ok || data.error) {
                alert(data.error || 'Failed to upload voice note.');
            }
        })
        .catch(err => {
            console.error('Voice upload failed:', err);
            alert('Failed to send voice note.');
        });

        resetRecordingUI();
    };

    try {
        mediaRecorder.stop();
    } catch (e) {
        console.error('Error stopping mediaRecorder:', e);
        resetRecordingUI();
    }
}

function resetRecordingUI() {
    clearInterval(recordingTimerInterval);
    recordingSeconds = 0;
    const textContainer = document.getElementById('textInputContainer');
    const voiceContainer = document.getElementById('voiceRecordingContainer');
    if (textContainer && voiceContainer) {
        voiceContainer.classList.remove('flex');
        voiceContainer.classList.add('hidden');
        textContainer.classList.remove('hidden');
    }
}

if (sendButton) {
    sendButton.addEventListener('click', sendMessage);
}

if (messageInput) {
    messageInput.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            sendMessage();
        }
    });

    // Mobile Virtual Keyboard auto-scroll triggers
    messageInput.addEventListener('focus', function () {
        setTimeout(() => scrollToBottom(true), 150);
        setTimeout(() => scrollToBottom(true), 350);
        setTimeout(() => scrollToBottom(true), 600);
    });

    messageInput.addEventListener('click', function () {
        setTimeout(() => scrollToBottom(true), 150);
    });
}

// Mobile viewport resize listener (tracks virtual keyboard show/hide)
if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', () => {
        setTimeout(() => scrollToBottom(true), 100);
        setTimeout(() => scrollToBottom(true), 300);
    });
}

const searchInput = document.getElementById('conversationSearch');
if (searchInput) {
    searchInput.addEventListener('input', function () {
        const query = searchInput.value.toLowerCase().trim();
        const items = document.querySelectorAll('.conversation-item');

        items.forEach(function (item) {
            const text = item.textContent.toLowerCase();
            item.style.display = text.includes(query) ? 'flex' : 'none';
        });
    });
}

// Multi-stage initial load scroll to handle dynamic font & image loading and init audio players
function initAllExistingAudioPlayers() {
    document.querySelectorAll('.custom-audio-player').forEach(initCustomAudioPlayer);
}

if (messagesContainer) {
    scrollToBottom(false);
    initAllExistingAudioPlayers();
    window.addEventListener('DOMContentLoaded', () => {
        scrollToBottom(false);
        initAllExistingAudioPlayers();
    });
    window.addEventListener('load', () => {
        scrollToBottom(false);
        initAllExistingAudioPlayers();
    });
    setTimeout(() => {
        scrollToBottom(false);
        initAllExistingAudioPlayers();
    }, 50);
    setTimeout(() => scrollToBottom(false), 150);
    setTimeout(() => scrollToBottom(false), 400);
}

// ====================================================
// ====================================================
// WebRTC 1-on-1 Voice & Video Calling Engine
// ====================================================
const rtcConfiguration = {
    iceServers: [
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' },
        { urls: 'stun:stun2.l.google.com:19302' },
        { urls: 'stun:stun3.l.google.com:19302' },
        { urls: 'stun:stun4.l.google.com:19302' },
        { urls: 'stun:global.stun.twilio.com:3478' }
    ],
    iceCandidatePoolSize: 10
};

let peerConnection = null;
let localStream = null;
let remoteStream = null;
let pendingIceCandidates = [];
let currentCallType = 'video';
let pendingIncomingOffer = null;
let callDurationInterval = null;
let callDurationSeconds = 0;
let isCallActive = false;
let isAudioMuted = false;
let isVideoMuted = false;
let isScreenSharing = false;
let currentCameraFacing = 'user';
let ringtoneAudioContext = null;
let ringtoneOscillator = null;



// Synthetic Ringtone using Web Audio API
function startRingtone() {
    try {
        stopRingtone();
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (!AudioCtx) return;
        ringtoneAudioContext = new AudioCtx();
        const gainNode = ringtoneAudioContext.createGain();
        gainNode.gain.setValueAtTime(0.08, ringtoneAudioContext.currentTime);
        gainNode.connect(ringtoneAudioContext.destination);

        function playBeep(freq, delay, duration) {
            const osc = ringtoneAudioContext.createOscillator();
            osc.type = 'sine';
            osc.frequency.setValueAtTime(freq, ringtoneAudioContext.currentTime + delay);
            osc.connect(gainNode);
            osc.start(ringtoneAudioContext.currentTime + delay);
            osc.stop(ringtoneAudioContext.currentTime + delay + duration);
        }

        let loopTime = 0;
        for (let cycle = 0; cycle < 10; cycle++) {
            playBeep(440, loopTime, 0.8);
            playBeep(480, loopTime, 0.8);
            loopTime += 1.2;
            playBeep(440, loopTime, 0.8);
            playBeep(480, loopTime, 0.8);
            loopTime += 3.0;
        }
    } catch (e) {
        console.warn('Ringtone could not start:', e);
    }
}

function stopRingtone() {
    if (ringtoneAudioContext) {
        try {
            ringtoneAudioContext.close();
        } catch (e) {}
        ringtoneAudioContext = null;
    }
}

function sendCallSignal(action, extra = {}) {
    const targetConvId = extra.conversation_id || pendingIncomingOffer?.conversation_id || conversationId;
    const payload = {
        action: action,
        conversation_id: targetConvId,
        ...extra
    };
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(payload));
    } else {
        console.warn('[LetsChat] Socket not open, buffering call signal:', action);
        pendingSocketQueue.push(payload);
        connectWebSocket();
    }
}

function ensureMediaPlaying(element) {
    if (!element) return;
    try {
        element.muted = false;
        element.volume = 1.0;
        const p = element.play();
        if (p !== undefined) {
            p.catch(() => {
                const retryPlay = () => {
                    element.play().catch(() => {});
                    window.removeEventListener('click', retryPlay);
                    window.removeEventListener('touchstart', retryPlay);
                };
                window.addEventListener('click', retryPlay, { once: true });
                window.addEventListener('touchstart', retryPlay, { once: true });
            });
        }
    } catch (e) {
        console.warn('ensureMediaPlaying error:', e);
    }
}

function formatSessionDescription(data, fallbackType = 'offer') {
    if (!data) return null;
    if (typeof data === 'string') {
        return new RTCSessionDescription({ type: fallbackType, sdp: data });
    }
    const type = data.type || fallbackType;
    const sdp = data.sdp || '';
    return new RTCSessionDescription({ type, sdp });
}

async function addOrQueueIceCandidate(candData) {
    if (!candData) return;
    try {
        let candObj = candData;
        if (typeof candData === 'string') {
            candObj = { candidate: candData };
        }
        if (peerConnection && peerConnection.remoteDescription && peerConnection.remoteDescription.type) {
            await peerConnection.addIceCandidate(new RTCIceCandidate(candObj));
        } else {
            pendingIceCandidates.push(candObj);
        }
    } catch (e) {
        console.warn('[WebRTC] Candidate error:', e);
    }
}

async function processPendingIceCandidates() {
    if (!peerConnection || !peerConnection.remoteDescription) return;
    while (pendingIceCandidates.length > 0) {
        const cand = pendingIceCandidates.shift();
        try {
            await peerConnection.addIceCandidate(new RTCIceCandidate(cand));
        } catch (e) {
            console.warn('[WebRTC] Queued candidate failed:', e);
        }
    }
}

async function createPeerConnection() {
    if (peerConnection) {
        try { peerConnection.close(); } catch (e) {}
    }

    peerConnection = new RTCPeerConnection(rtcConfiguration);
    remoteStream = new MediaStream();

    const remoteVideo = document.getElementById('remoteVideo');
    const remoteAudio = document.getElementById('remoteAudio');

    if (remoteVideo) {
        remoteVideo.srcObject = remoteStream;
    }
    if (remoteAudio) {
        remoteAudio.srcObject = remoteStream;
    }

    peerConnection.onicecandidate = (event) => {
        if (event.candidate) {
            sendCallSignal('ice_candidate', {
                candidate: {
                    candidate: event.candidate.candidate,
                    sdpMid: event.candidate.sdpMid,
                    sdpMLineIndex: event.candidate.sdpMLineIndex,
                    usernameFragment: event.candidate.usernameFragment
                }
            });
        }
    };

    peerConnection.ontrack = (event) => {
        console.log('[WebRTC] Received remote track:', event.track.kind);
        if (!remoteStream) {
            remoteStream = new MediaStream();
        }

        if (event.streams && event.streams[0]) {
            event.streams[0].getTracks().forEach(t => {
                if (!remoteStream.getTracks().some(existing => existing.id === t.id)) {
                    remoteStream.addTrack(t);
                }
            });
        }
        if (event.track) {
            if (!remoteStream.getTracks().some(existing => existing.id === event.track.id)) {
                remoteStream.addTrack(event.track);
            }
        }

        const rVideo = document.getElementById('remoteVideo');
        const rAudio = document.getElementById('remoteAudio');

        if (rVideo) {
            if (rVideo.srcObject !== remoteStream) {
                rVideo.srcObject = remoteStream;
            }
            ensureMediaPlaying(rVideo);
        }

        if (rAudio) {
            if (rAudio.srcObject !== remoteStream) {
                rAudio.srcObject = remoteStream;
            }
            ensureMediaPlaying(rAudio);
        }

        const placeholder = document.getElementById('audioCallAvatarPlaceholder');
        if (placeholder) {
            const hasVideo = remoteStream.getVideoTracks().some(t => t.enabled && t.readyState === 'live');
            if (hasVideo && currentCallType === 'video') {
                placeholder.classList.add('hidden');
            } else if (currentCallType === 'audio') {
                placeholder.classList.remove('hidden');
            }
        }
    };

    peerConnection.oniceconnectionstatechange = () => {
        console.log('[WebRTC] ICE State:', peerConnection.iceConnectionState);
        if (peerConnection.iceConnectionState === 'connected' || peerConnection.iceConnectionState === 'completed') {
            stopRingtone();
            startCallDurationTimer();
            const rVideo = document.getElementById('remoteVideo');
            const rAudio = document.getElementById('remoteAudio');
            if (rVideo) ensureMediaPlaying(rVideo);
            if (rAudio) ensureMediaPlaying(rAudio);
        } else if (peerConnection.iceConnectionState === 'failed') {
            console.warn('[WebRTC] ICE failed');
            if (isCallActive) {
                endCall();
            }
        }
    };

    peerConnection.onconnectionstatechange = () => {
        console.log('[WebRTC] Connection State:', peerConnection.connectionState);
        if (peerConnection.connectionState === 'connected') {
            stopRingtone();
            startCallDurationTimer();
            const rVideo = document.getElementById('remoteVideo');
            const rAudio = document.getElementById('remoteAudio');
            if (rVideo) ensureMediaPlaying(rVideo);
            if (rAudio) ensureMediaPlaying(rAudio);
        } else if (peerConnection.connectionState === 'failed') {
            console.warn('[WebRTC] Connection failed');
            if (isCallActive) {
                endCall();
            }
        }
    };

    if (localStream) {
        localStream.getTracks().forEach((track) => {
            track.enabled = true;
            try {
                peerConnection.addTrack(track, localStream);
            } catch (e) {
                console.warn('addTrack error:', e);
            }
        });
    }

    try {
        peerConnection.getTransceivers().forEach(tr => {
            tr.direction = 'sendrecv';
        });
    } catch (e) {}

    return peerConnection;
}

async function startCall(callType = 'video') {
    if (isCallActive) {
        if (window.showGlobalToast) window.showGlobalToast('Already in a call');
        return;
    }

    currentCallType = callType;
    try {
        const rVideo = document.getElementById('remoteVideo');
        const rAudio = document.getElementById('remoteAudio');
        if (rVideo) ensureMediaPlaying(rVideo);
        if (rAudio) ensureMediaPlaying(rAudio);

        let constraints = {
            audio: true,
            video: callType === 'video' ? { facingMode: currentCameraFacing } : false
        };

        try {
            localStream = await getCrossBrowserUserMedia(constraints);
        } catch (mediaErr) {
            console.warn('Initial constraints fallback:', mediaErr);
            localStream = await getCrossBrowserUserMedia({ audio: true, video: callType === 'video' });
        }

        const localVideo = document.getElementById('localVideo');
        if (localVideo) {
            localVideo.srcObject = localStream;
            localVideo.muted = true;
            localVideo.play().catch(() => {});
        }

        const localContainer = document.getElementById('localVideoContainer');
        if (localContainer) {
            localContainer.style.display = callType === 'video' ? 'block' : 'none';
        }

        await createPeerConnection();

        showActiveCallOverlay('Calling...');

        const offer = await peerConnection.createOffer({
            offerToReceiveAudio: true,
            offerToReceiveVideo: callType === 'video',
            voiceActivityDetection: true
        });
        await peerConnection.setLocalDescription(offer);

        sendCallSignal('call_offer', {
            call_type: callType,
            sdp: {
                type: offer.type || 'offer',
                sdp: offer.sdp
            }
        });

        isCallActive = true;
    } catch (err) {
        console.error('Failed to start call:', err);
        showMediaPermissionHelp(err.name === 'NotAllowedError' ? 'denied' : 'insecure');
        endCall();
    }
}

async function handleCallSignal(data) {
    if (data.sender === currentUsername) return;

    switch (data.action) {
        case 'call_offer':
            if (isCallActive) {
                sendCallSignal('call_busy');
                return;
            }
            pendingIncomingOffer = data;
            currentCallType = data.call_type || 'video';
            showIncomingCallDialog(data);
            break;

        case 'call_answer':
            if (peerConnection && data.sdp) {
                try {
                    const desc = formatSessionDescription(data.sdp, 'answer');
                    await peerConnection.setRemoteDescription(desc);
                    await processPendingIceCandidates();
                    startCallDurationTimer();
                    stopRingtone();
                    const rVideo = document.getElementById('remoteVideo');
                    const rAudio = document.getElementById('remoteAudio');
                    if (rVideo) ensureMediaPlaying(rVideo);
                    if (rAudio) ensureMediaPlaying(rAudio);
                } catch (err) {
                    console.error('Error setting remote answer:', err);
                }
            }
            break;

        case 'ice_candidate':
            if (data.candidate) {
                await addOrQueueIceCandidate(data.candidate);
            }
            break;

        case 'call_reject':
            stopRingtone();
            if (window.showGlobalToast) window.showGlobalToast('Call declined', true);
            endCall(false);
            break;

        case 'call_busy':
            stopRingtone();
            if (window.showGlobalToast) window.showGlobalToast('User is busy on another call', true);
            endCall(false);
            break;

        case 'call_end':
            stopRingtone();
            if (window.showGlobalToast) window.showGlobalToast('Call ended');
            endCall(false);
            break;
    }
}

function showIncomingCallDialog(data) {
    const modal = document.getElementById('incomingCallModal');
    const nameEl = document.getElementById('incomingCallerName');
    const typeEl = document.getElementById('incomingCallTypeLabel');
    const initialEl = document.getElementById('incomingCallerInitial');
    const avatarEl = document.getElementById('incomingCallerAvatar');

    if (nameEl) nameEl.textContent = data.sender || 'Incoming Call';
    if (typeEl) {
        typeEl.innerHTML = `
            <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
            <span>Incoming ${data.call_type === 'video' ? 'Video' : 'Voice'} Call</span>
        `;
    }
    if (avatarEl && data.sender_avatar) {
        avatarEl.src = data.sender_avatar;
        avatarEl.classList.remove('hidden');
        if (initialEl) initialEl.classList.add('hidden');
    } else if (initialEl) {
        initialEl.textContent = (data.sender || '?').charAt(0).toUpperCase();
        initialEl.classList.remove('hidden');
        if (avatarEl) avatarEl.classList.add('hidden');
    }

    if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }
    startRingtone();
}

function hideIncomingCallDialog() {
    stopRingtone();
    const modal = document.getElementById('incomingCallModal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
    pendingIncomingOffer = null;
}

function rejectIncomingCall() {
    hideIncomingCallDialog();
    sendCallSignal('call_reject');
}

async function acceptIncomingCall() {
    if (!pendingIncomingOffer) return;

    const offerData = pendingIncomingOffer;
    hideIncomingCallDialog();

    // If incoming call is for a different conversation than the currently open one, route to it
    if (offerData.conversation_id && String(offerData.conversation_id) !== String(conversationId)) {
        sessionStorage.setItem('pending_incoming_offer', JSON.stringify(offerData));
        window.location.href = `/?conversation=${offerData.conversation_id}&auto_call_accept=1`;
        return;
    }

    try {
        const rVideo = document.getElementById('remoteVideo');
        const rAudio = document.getElementById('remoteAudio');
        if (rVideo) ensureMediaPlaying(rVideo);
        if (rAudio) ensureMediaPlaying(rAudio);

        currentCallType = offerData.call_type || 'video';
        let constraints = {
            audio: true,
            video: currentCallType === 'video' ? { facingMode: currentCameraFacing } : false
        };

        try {
            localStream = await getCrossBrowserUserMedia(constraints);
        } catch (mediaErr) {
            console.warn('Initial accept constraints fallback:', mediaErr);
            localStream = await getCrossBrowserUserMedia({ audio: true, video: currentCallType === 'video' });
        }

        const localVideo = document.getElementById('localVideo');
        if (localVideo) {
            localVideo.srcObject = localStream;
            localVideo.muted = true;
            localVideo.play().catch(() => {});
        }

        const localContainer = document.getElementById('localVideoContainer');
        if (localContainer) {
            localContainer.style.display = currentCallType === 'video' ? 'block' : 'none';
        }

        await createPeerConnection();
        showActiveCallOverlay('Connecting...');

        const desc = formatSessionDescription(offerData.sdp, 'offer');
        await peerConnection.setRemoteDescription(desc);
        await processPendingIceCandidates();

        const answer = await peerConnection.createAnswer({
            voiceActivityDetection: true
        });
        await peerConnection.setLocalDescription(answer);

        sendCallSignal('call_answer', {
            sdp: {
                type: answer.type || 'answer',
                sdp: answer.sdp
            }
        });

        isCallActive = true;
        startCallDurationTimer();
    } catch (err) {
        console.error('Failed to accept call:', err);
        showMediaPermissionHelp(err.name === 'NotAllowedError' ? 'denied' : 'insecure');
        endCall();
    }
}

function showActiveCallOverlay(statusText = 'Connected') {
    const overlay = document.getElementById('activeCallOverlay');
    const timer = document.getElementById('callDurationTimer');
    const targetName = document.getElementById('callTargetName');
    const placeholder = document.getElementById('audioCallAvatarPlaceholder');

    if (timer) timer.textContent = statusText;
    if (targetName) targetName.textContent = currentCallType === 'video' ? 'Video Call' : 'Voice Call';

    if (placeholder) {
        if (currentCallType === 'audio') {
            placeholder.classList.remove('hidden');
        } else {
            placeholder.classList.add('hidden');
        }
    }

    if (overlay) {
        overlay.classList.remove('hidden');
    }
}

function startCallDurationTimer() {
    clearInterval(callDurationInterval);
    callDurationSeconds = 0;
    const timer = document.getElementById('callDurationTimer');
    callDurationInterval = setInterval(() => {
        callDurationSeconds++;
        const mins = Math.floor(callDurationSeconds / 60);
        const secs = callDurationSeconds % 60;
        if (timer) {
            timer.textContent = `${mins < 10 ? '0' : ''}${mins}:${secs < 10 ? '0' : ''}${secs}`;
        }
    }, 1000);
}

function toggleCallMute() {
    if (!localStream) return;
    const audioTrack = localStream.getAudioTracks()[0];
    if (audioTrack) {
        isAudioMuted = !isAudioMuted;
        audioTrack.enabled = !isAudioMuted;

        const micOnIcon = document.getElementById('micOnIcon');
        const micOffIcon = document.getElementById('micOffIcon');
        const muteBtn = document.getElementById('callMuteBtn');

        if (isAudioMuted) {
            if (micOnIcon) micOnIcon.classList.add('hidden');
            if (micOffIcon) micOffIcon.classList.remove('hidden');
            if (muteBtn) muteBtn.classList.add('bg-rose-500/20', 'border-rose-500/40');
        } else {
            if (micOnIcon) micOnIcon.classList.remove('hidden');
            if (micOffIcon) micOffIcon.classList.add('hidden');
            if (muteBtn) muteBtn.classList.remove('bg-rose-500/20', 'border-rose-500/40');
        }
    }
}

function toggleCallCamera() {
    if (!localStream) return;
    const videoTrack = localStream.getVideoTracks()[0];
    const localBadge = document.getElementById('localVideoMutedBadge');
    const camOnIcon = document.getElementById('cameraOnIcon');
    const camOffIcon = document.getElementById('cameraOffIcon');
    const camBtn = document.getElementById('callVideoBtn');

    if (videoTrack) {
        isVideoMuted = !isVideoMuted;
        videoTrack.enabled = !isVideoMuted;

        if (isVideoMuted) {
            if (localBadge) localBadge.classList.remove('hidden');
            if (camOnIcon) camOnIcon.classList.add('hidden');
            if (camOffIcon) camOffIcon.classList.remove('hidden');
            if (camBtn) camBtn.classList.add('bg-rose-500/20', 'border-rose-500/40');
        } else {
            if (localBadge) localBadge.classList.add('hidden');
            if (camOnIcon) camOnIcon.classList.remove('hidden');
            if (camOffIcon) camOffIcon.classList.add('hidden');
            if (camBtn) camBtn.classList.remove('bg-rose-500/20', 'border-rose-500/40');
        }
    }
}

async function toggleCallScreenShare() {
    if (!peerConnection || !localStream) return;

    if (!isScreenSharing) {
        try {
            const screenStream = await navigator.mediaDevices.getDisplayMedia({ video: true });
            const screenTrack = screenStream.getVideoTracks()[0];

            const senders = peerConnection.getSenders();
            const videoSender = senders.find(s => s.track && s.track.kind === 'video');
            if (videoSender) {
                videoSender.replaceTrack(screenTrack);
            }

            const localVideo = document.getElementById('localVideo');
            if (localVideo) localVideo.srcObject = screenStream;

            screenTrack.onended = () => {
                revertToCameraTrack(videoSender);
            };

            isScreenSharing = true;
            const shareBtn = document.getElementById('callScreenShareBtn');
            if (shareBtn) shareBtn.classList.add('bg-blue-600', 'text-white');
        } catch (err) {
            console.error('Screen sharing canceled/failed:', err);
        }
    } else {
        const senders = peerConnection.getSenders();
        const videoSender = senders.find(s => s.track && s.track.kind === 'video');
        revertToCameraTrack(videoSender);
    }
}

function revertToCameraTrack(videoSender) {
    if (!localStream) return;
    const cameraTrack = localStream.getVideoTracks()[0];
    if (videoSender && cameraTrack) {
        videoSender.replaceTrack(cameraTrack);
    }
    const localVideo = document.getElementById('localVideo');
    if (localVideo) localVideo.srcObject = localStream;
    isScreenSharing = false;

    const shareBtn = document.getElementById('callScreenShareBtn');
    if (shareBtn) shareBtn.classList.remove('bg-blue-600', 'text-white');
}

async function flipCallCamera() {
    if (!localStream || currentCallType !== 'video') return;
    currentCameraFacing = currentCameraFacing === 'user' ? 'environment' : 'user';

    try {
        const newStream = await navigator.mediaDevices.getUserMedia({
            audio: false,
            video: { facingMode: currentCameraFacing }
        });
        const newVideoTrack = newStream.getVideoTracks()[0];

        const oldVideoTrack = localStream.getVideoTracks()[0];
        if (oldVideoTrack) {
            localStream.removeTrack(oldVideoTrack);
            oldVideoTrack.stop();
        }
        localStream.addTrack(newVideoTrack);

        const localVideo = document.getElementById('localVideo');
        if (localVideo) localVideo.srcObject = localStream;

        if (peerConnection) {
            const videoSender = peerConnection.getSenders().find(s => s.track && s.track.kind === 'video');
            if (videoSender) {
                videoSender.replaceTrack(newVideoTrack);
            }
        }
    } catch (err) {
        console.error('Failed to flip camera:', err);
    }
}

function endCall(notifyPeer = true) {
    stopRingtone();
    if (notifyPeer && isCallActive) {
        sendCallSignal('call_end');
    }

    if (localStream) {
        localStream.getTracks().forEach(track => track.stop());
        localStream = null;
    }

    if (remoteStream) {
        remoteStream.getTracks().forEach(track => track.stop());
        remoteStream = null;
    }

    if (peerConnection) {
        peerConnection.close();
        peerConnection = null;
    }

    clearInterval(callDurationInterval);
    callDurationSeconds = 0;
    pendingIceCandidates = [];
    isCallActive = false;
    isAudioMuted = false;
    isVideoMuted = false;
    isScreenSharing = false;

    const overlay = document.getElementById('activeCallOverlay');
    if (overlay) overlay.classList.add('hidden');

    hideIncomingCallDialog();
}

window.startCall = startCall;
window.acceptIncomingCall = acceptIncomingCall;
window.rejectIncomingCall = rejectIncomingCall;
window.toggleCallMute = toggleCallMute;
window.toggleCallCamera = toggleCallCamera;
window.toggleCallScreenShare = toggleCallScreenShare;
window.flipCallCamera = flipCallCamera;
window.endCall = endCall;

// Auto-accept incoming call if navigated with auto_call_accept=1
window.addEventListener('DOMContentLoaded', () => {
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('auto_call_accept') === '1') {
        const storedOffer = sessionStorage.getItem('pending_incoming_offer');
        if (storedOffer) {
            try {
                pendingIncomingOffer = JSON.parse(storedOffer);
                sessionStorage.removeItem('pending_incoming_offer');
                setTimeout(() => {
                    acceptIncomingCall();
                }, 400);
            } catch (e) {
                console.warn('Auto accept failed:', e);
            }
        }
    }
});