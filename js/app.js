/* N.E.U.R.O.N frontend — local Whisper STT via PCM streaming */

(() => {
  "use strict";

  const canvas = document.getElementById("blob-canvas");
  const ctx = canvas.getContext("2d");
  const statusEl = document.getElementById("status");
  const transcriptEl = document.getElementById("transcript");
  const clockEl = document.getElementById("clock");
  const meterFill = document.getElementById("mic-meter-fill");

  const responseEl = document.getElementById("response");
  const brainStatusEl = document.getElementById("brain-status");

  let active = false;
  let lastWordAt = 0;
  let speechEnergy = 0;
  let muted = false;
  let busy = false;
  let lastSent = "";
  let lastSentAt = 0;
  let sttReady = false;
  let useWhisper = true;
  let speaking = false;
  let currentAudio = null;

  function isStopTalk(text) {
    return /\b(stop talking|stop speaking|be quiet|shut up|silence|stop\s+neuron)\b/i.test(
      text || ""
    );
  }

  function stopTalking(announce) {
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    if (currentAudio) {
      try {
        currentAudio.pause();
        currentAudio.currentTime = 0;
        currentAudio.src = "";
      } catch (_) {}
      currentAudio = null;
    }
    speaking = false;
    muted = false;
    sendControl({ mute: false });
    if (announce) {
      responseEl.textContent = announce;
    }
    if (active) setStatus("LISTENING");
  }

  function speakable(text) {
    // Strip markdown so TTS doesn't read hashes/stars for minutes.
    let t = String(text || "")
      .replace(/```[\s\S]*?```/g, " ")
      .replace(/[#*_`>]/g, " ")
      .replace(/\n+/g, ". ")
      .replace(/\s+/g, " ")
      .trim();
    if (t.length > 320) t = t.slice(0, 300).replace(/\s+\S*$/, "") + ".";
    return t;
  }

  let audioCtx = null;
  let mediaStream = null;
  let processor = null;
  let micSource = null;

  const WORD_HOLD_MS = 900;
  const DEDUPE_MS = 8000;
  const TARGET_RATE = 16000;

  // ------------------------------------------------------------------
  // Brain connection (backend WebSocket)
  // ------------------------------------------------------------------
  let ws = null;

  function connectBrain() {
    try {
      if (ws) {
        try { ws.onclose = null; ws.close(); } catch (_) {}
      }
    } catch (_) {}

    ws = new WebSocket(`ws://${location.host}/ws`);
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      brainStatusEl.textContent = "BRAIN: ONLINE";
      brainStatusEl.classList.remove("brain-offline");
      brainStatusEl.classList.add("brain-online");
      if (!sttReady) setStatus("LOADING WHISPER...");
    };

    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch (_) {
        return;
      }

      if (msg.type === "stt_status") {
        useWhisper = msg.engine === "whisper";
        sttReady = !!msg.ready;
        if (msg.backend) window.__sttBackend = msg.backend;
        if (sttReady) {
          const tag = (msg.backend || "whisper").toUpperCase();
          setStatus("LISTENING (" + tag + ")");
          active = true;
        } else if (useWhisper) {
          setStatus("LOADING WHISPER...");
        } else if (msg.error) {
          setStatus("WHISPER FAILED — BROWSER STT");
          startBrowserRecognition();
        }
        return;
      }

      if (msg.type === "hearing") {
        if (!muted) {
          lastWordAt = Date.now();
          speechEnergy = Math.max(speechEnergy, Math.min(1, (msg.level || 0.4) * 1.6));
          if (!busy) setStatus("HEARING YOU...");
        }
        return;
      }

      if (msg.type === "partial" && msg.text) {
        transcriptEl.textContent = msg.text;
        transcriptEl.classList.add("interim");
        lastWordAt = Date.now();
        speechEnergy = Math.max(speechEnergy, 0.5);
        if (!busy && !muted) setStatus("HEARING YOU...");
        return;
      }

      if (msg.type === "status" && msg.text) {
        // Rejected speech: show what was ignored so it doesn't feel "deaf"
        if (msg.rejected && msg.heard) {
          transcriptEl.textContent = "(" + msg.heard + ")";
          transcriptEl.classList.add("interim");
        }
        if (!(busy && msg.text === "LISTENING")) {
          setStatus(msg.text);
        }
        return;
      }

      if (msg.type === "heard" && msg.text) {
        transcriptEl.textContent = msg.text;
        transcriptEl.classList.remove("interim");
        lastWordAt = Date.now();
        speechEnergy = 1;
        // Barge-in: cancel TTS immediately when user says stop talking.
        if (isStopTalk(msg.text)) {
          stopTalking();
        }
        lastSent = msg.text.toLowerCase().replace(/\s+/g, " ");
        lastSentAt = Date.now();
        busy = true;
        setStatus("WORKING...");
        return;
      }

      if (msg.type === "stop_speech") {
        busy = false;
        stopTalking(msg.text || "Okay.");
        if (msg.heard) {
          transcriptEl.textContent = msg.heard;
          transcriptEl.classList.remove("interim");
        }
        return;
      }

      if (msg.type === "response") {
        busy = false;
        if (msg.heard) {
          transcriptEl.textContent = msg.heard;
          transcriptEl.classList.remove("interim");
        }
        if (msg.stop_speech || isStopTalk(msg.heard || "")) {
          stopTalking(msg.text || "Okay.");
          return;
        }
        if (msg.text) {
          responseEl.textContent = msg.text;
          if (msg.audio_url) {
            try {
              if (currentAudio) {
                try {
                  currentAudio.pause();
                } catch (_) {}
              }
              const a = new Audio(msg.audio_url);
              currentAudio = a;
              a.onended = a.onerror = () => {
                if (currentAudio === a) currentAudio = null;
                speaking = false;
                if (active && !muted) setStatus("LISTENING");
              };
              speaking = true;
              a.play().catch(() => speak(speakable(msg.text)));
            } catch (_) {
              speak(speakable(msg.text));
            }
          } else {
            speak(speakable(msg.text));
          }
        } else if (active && !muted) {
          setStatus("LISTENING");
        }
      }
      if (msg.type === "confirm") {
        busy = false;
        if (msg.heard) transcriptEl.textContent = msg.heard;
        responseEl.textContent = msg.text || msg.reason || "Confirm?";
        speak(speakable(msg.text || "Please confirm."));
        setStatus("CONFIRM REQUIRED");
      }
    };

    ws.onclose = () => {
      busy = false;
      brainStatusEl.textContent = "BRAIN: OFFLINE";
      brainStatusEl.classList.remove("brain-online");
      brainStatusEl.classList.add("brain-offline");
      setStatus("RECONNECTING...");
      setTimeout(connectBrain, 1500);
    };

    ws.onerror = () => ws.close();
  }

  function sendControl(payload) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "control", ...payload }));
    }
  }

  function sendToBrain(text) {
    const cleaned = (text || "").trim();
    if (!cleaned) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;

    // Always allow stop talking, even while WORKING / speaking.
    if (isStopTalk(cleaned)) {
      stopTalking();
      ws.send(JSON.stringify({ type: "transcript", text: cleaned }));
      return;
    }

    const now = Date.now();
    const norm = cleaned.toLowerCase().replace(/\s+/g, " ");
    if (busy) {
      setStatus("WORKING...");
      return;
    }
    if (norm === lastSent && now - lastSentAt < DEDUPE_MS) return;

    lastSent = norm;
    lastSentAt = now;
    busy = true;
    setStatus("WORKING...");
    ws.send(JSON.stringify({ type: "transcript", text: cleaned }));
  }

  // ------------------------------------------------------------------
  // Voice reply — keep mic open so "stop talking" can barge in
  // ------------------------------------------------------------------
  function speak(text) {
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();

    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.15;
    u.pitch = 0.85;
    const voice = window.speechSynthesis
      .getVoices()
      .find((v) => /en(-|_)(GB|US)/i.test(v.lang) && /male|david|george|ryan/i.test(v.name));
    if (voice) u.voice = voice;

    // Do NOT mute STT for the whole utterance — user must be able to say
    // "stop talking". Echo cancellation handles most self-hearing.
    speaking = true;
    muted = false;
    sendControl({ mute: false });

    u.onend = u.onerror = () => {
      speaking = false;
      muted = false;
      sendControl({ mute: false });
      if (active) setStatus("LISTENING");
    };

    window.speechSynthesis.speak(u);
  }

  // ------------------------------------------------------------------
  // Canvas / clock / status
  // ------------------------------------------------------------------
  function resize() {
    const dpr = window.devicePixelRatio || 1;
    canvas.width = window.innerWidth * dpr;
    canvas.height = window.innerHeight * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  window.addEventListener("resize", resize);
  resize();

  setInterval(() => {
    clockEl.textContent = new Date().toLocaleTimeString("en-GB");
  }, 1000);

  function setStatus(text) {
    statusEl.textContent = text;
  }

  // ------------------------------------------------------------------
  // Mic capture → 16 kHz Int16 PCM → WebSocket (Whisper)
  // ------------------------------------------------------------------
  function downsampleTo16k(float32, inRate) {
    if (inRate === TARGET_RATE) return float32;
    const ratio = inRate / TARGET_RATE;
    const outLen = Math.floor(float32.length / ratio);
    const out = new Float32Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const start = Math.floor(i * ratio);
      const end = Math.floor((i + 1) * ratio);
      let sum = 0;
      let n = 0;
      for (let j = start; j < end && j < float32.length; j++) {
        sum += float32[j];
        n++;
      }
      out[i] = n ? sum / n : 0;
    }
    return out;
  }

  function floatTo16BitPCM(float32) {
    const buf = new ArrayBuffer(float32.length * 2);
    const view = new DataView(buf);
    for (let i = 0; i < float32.length; i++) {
      let s = Math.max(-1, Math.min(1, float32[i]));
      view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return buf;
  }

  async function ensureAudioRunning() {
    if (!audioCtx) return false;
    if (audioCtx.state === "suspended") {
      try {
        await audioCtx.resume();
      } catch (_) {}
    }
    return audioCtx.state === "running";
  }

  function armMicOnGesture() {
    ensureAudioRunning().then((ok) => {
      if (ok && sttReady && active && !busy) {
        setStatus("LISTENING");
      } else if (ok && sttReady) {
        const tag = (window.__sttBackend || "whisper").toUpperCase();
        if (!busy) setStatus("LISTENING (" + tag + ")");
      }
    });
  }

  async function startWhisperMic() {
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (_) {
      setStatus("MIC PERMISSION DENIED");
      return false;
    }

    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    await ensureAudioRunning();
    micSource = audioCtx.createMediaStreamSource(mediaStream);

    // Meter
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    analyser.smoothingTimeConstant = 0.5;
    micSource.connect(analyser);
    const meterData = new Uint8Array(analyser.frequencyBinCount);
    (function tickMeter() {
      requestAnimationFrame(tickMeter);
      analyser.getByteFrequencyData(meterData);
      let sum = 0;
      for (let i = 2; i < 40; i++) sum += meterData[i];
      const level = sum / (38 * 255);
      meterFill.style.width = Math.min(100, level * 220) + "%";
    })();

    // ScriptProcessor is deprecated but universal and simple for PCM streaming.
    const bufferSize = 4096;
    processor = audioCtx.createScriptProcessor(bufferSize, 1, 1);
    processor.onaudioprocess = (e) => {
      // Keep streaming while WORKING so barge-in / VAD still hear the user.
      // Server ignores duplicate commands while busy.
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      if (!sttReady) return;
      if (muted && !speaking) return;
      ensureAudioRunning();
      const input = e.inputBuffer.getChannelData(0);
      const down = downsampleTo16k(input, audioCtx.sampleRate);
      try {
        ws.send(floatTo16BitPCM(down));
      } catch (_) {}
    };
    micSource.connect(processor);
    processor.connect(audioCtx.destination); // required for some browsers to fire

    // Mute the tap to speakers so we don't get feedback loop of silence.
    const gain = audioCtx.createGain();
    gain.gain.value = 0;
    processor.disconnect();
    micSource.connect(processor);
    processor.connect(gain);
    gain.connect(audioCtx.destination);

    active = true;
    if (sttReady) setStatus("LISTENING");
    else setStatus("LOADING EARS...");
    return true;
  }

  // Browser SpeechRecognition fallback if Whisper can't load
  function startBrowserRecognition() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      setStatus("SPEECH RECOGNITION UNAVAILABLE");
      return;
    }
    const recognition = new SR();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    recognition.onstart = () => {
      active = true;
      setStatus("LISTENING (BROWSER)");
    };
    recognition.onresult = (e) => {
      let interim = "";
      let final = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) final += t;
        else interim += t;
      }
      const heard = (final || interim).trim();
      if (/[a-zA-Z]{2,}/.test(heard)) {
        lastWordAt = Date.now();
        speechEnergy = 1;
        setStatus("HEARING YOU...");
      }
      if (final && /[a-zA-Z]{2,}/.test(final)) {
        transcriptEl.textContent = final.trim();
        transcriptEl.classList.remove("interim");
        sendToBrain(final.trim());
      } else if (interim && /[a-zA-Z]{2,}/.test(interim)) {
        transcriptEl.textContent = interim.trim();
        transcriptEl.classList.add("interim");
      }
    };
    recognition.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        setStatus("MIC PERMISSION DENIED");
        active = false;
      }
    };
    recognition.onend = () => {
      if (!muted) {
        setTimeout(() => {
          try {
            recognition.start();
          } catch (_) {}
        }, 120);
      }
    };
    try {
      recognition.start();
    } catch (_) {}
  }

  // ------------------------------------------------------------------
  async function boot() {
    setStatus("STARTING...");
    connectBrain();
    const ok = await startWhisperMic();
    if (!ok) return;

    // Edge/Chrome often suspend AudioContext until a click — click the core to arm mic.
    canvas.addEventListener("pointerdown", armMicOnGesture);
    window.addEventListener("focus", armMicOnGesture);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) armMicOnGesture();
    });
    armMicOnGesture();

    // Safety: never stay WORKING forever (would look like "deaf")
    setInterval(() => {
      if (busy && Date.now() - lastSentAt > 90000) {
        busy = false;
        if (active && !muted) setStatus("LISTENING");
      }
      ensureAudioRunning();
    }, 5000);

    // If Whisper never becomes ready within 3 minutes, fall back.
    // OpenAI Whisper turbo first load on GPU can exceed 45s.
    setTimeout(() => {
      if (!sttReady) {
        useWhisper = false;
        setStatus("WHISPER TIMEOUT — BROWSER STT");
        startBrowserRecognition();
      }
    }, 180000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  // ------------------------------------------------------------------
  // Blob rendering
  // ------------------------------------------------------------------
  const POINTS = 160;
  let t = 0;

  function blobRadius(angle, base, amp) {
    if (amp <= 0) return base;
    return (
      base +
      amp *
        (Math.sin(angle * 3 + t * 1.7) * 0.45 +
          Math.sin(angle * 5 - t * 2.3) * 0.3 +
          Math.sin(angle * 8 + t * 3.1) * 0.15 +
          Math.sin(angle * 13 - t * 4.7) * 0.1)
    );
  }

  function draw() {
    requestAnimationFrame(draw);
    t += 0.016;

    const hearing = Date.now() - lastWordAt < WORD_HOLD_MS && speechEnergy > 0.05;
    if (!hearing) {
      speechEnergy *= 0.88;
      if (speechEnergy < 0.05) speechEnergy = 0;
      if (active && !muted && !busy && statusEl.textContent === "HEARING YOU...") {
        setStatus("LISTENING");
      }
    }

    const energy = hearing ? Math.max(0.35, speechEnergy) : 0.12;
    const w = window.innerWidth;
    const h = window.innerHeight;
    ctx.clearRect(0, 0, w, h);

    const base = Math.min(w, h) * 0.21;
    const wobbleAmp = hearing ? base * (0.08 + energy * 0.28) : 0;
    const shake = hearing ? energy * 7 : 0;
    const cx = w / 2 + (Math.random() - 0.5) * shake;
    const cy = h / 2 + (Math.random() - 0.5) * shake;

    const halo = ctx.createRadialGradient(cx, cy, base * 0.4, cx, cy, base * (2.1 + (hearing ? energy : 0)));
    halo.addColorStop(0, `rgba(0, 229, 255, ${0.10 + (hearing ? energy * 0.16 : 0)})`);
    halo.addColorStop(1, "rgba(0, 229, 255, 0)");
    ctx.fillStyle = halo;
    ctx.fillRect(0, 0, w, h);

    drawRing(cx, cy, base * 1.45, t * 0.35, 0.28, hearing ? energy : 0);
    drawRing(cx, cy, base * 1.62, -t * 0.22, 0.16, hearing ? energy : 0);

    ctx.beginPath();
    for (let i = 0; i <= POINTS; i++) {
      const a = (i / POINTS) * Math.PI * 2;
      const r = blobRadius(a, base, wobbleAmp);
      const x = cx + Math.cos(a) * r;
      const y = cy + Math.sin(a) * r;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.closePath();

    const body = ctx.createRadialGradient(cx, cy, 0, cx, cy, base * 1.15);
    body.addColorStop(0, `rgba(190, 250, 255, ${0.85 + (hearing ? energy * 0.15 : 0)})`);
    body.addColorStop(0.35, `rgba(0, 229, 255, ${0.5 + (hearing ? energy * 0.3 : 0)})`);
    body.addColorStop(0.8, "rgba(0, 120, 200, 0.22)");
    body.addColorStop(1, "rgba(0, 60, 120, 0)");
    ctx.fillStyle = body;
    ctx.shadowColor = "rgba(0, 229, 255, 0.9)";
    ctx.shadowBlur = 30 + (hearing ? energy * 50 : 0);
    ctx.fill();
    ctx.shadowBlur = 0;

    ctx.strokeStyle = `rgba(0, 229, 255, ${0.35 + (hearing ? energy * 0.5 : 0)})`;
    ctx.lineWidth = 1.5;
    ctx.stroke();

    const coreR = base * (0.30 + (hearing ? energy * 0.10 : 0));
    const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR);
    core.addColorStop(0, "rgba(255, 255, 255, 0.95)");
    core.addColorStop(0.5, "rgba(160, 245, 255, 0.7)");
    core.addColorStop(1, "rgba(0, 229, 255, 0)");
    ctx.fillStyle = core;
    ctx.beginPath();
    ctx.arc(cx, cy, coreR, 0, Math.PI * 2);
    ctx.fill();
  }

  function drawRing(cx, cy, radius, rotation, alpha, energy) {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(rotation);
    ctx.strokeStyle = `rgba(0, 229, 255, ${alpha + energy * 0.2})`;
    ctx.lineWidth = 1;
    for (let s = 0; s < 3; s++) {
      ctx.beginPath();
      const start = (s / 3) * Math.PI * 2;
      ctx.arc(0, 0, radius, start, start + Math.PI * 0.42);
      ctx.stroke();
    }
    ctx.restore();
  }

  draw();
})();
