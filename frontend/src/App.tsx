import { useEffect, useRef, useState } from "react";

declare global {
  interface Window {
    neuronDesktop?: { onConfig: (cb: (c: { brain: string }) => void) => void };
  }
}

type WsMsg = {
  type: string;
  text?: string | null;
  heard?: string;
  acted?: boolean;
  ready?: boolean;
  engine?: string;
  backend?: string;
  audio_url?: string;
  tts_engine?: string;
  action?: string;
  reason?: string;
};

export function App() {
  const [status, setStatus] = useState("STARTING...");
  const [brain, setBrain] = useState("BRAIN: OFFLINE");
  const [heard, setHeard] = useState("");
  const [reply, setReply] = useState("");
  const [brainBase, setBrainBase] = useState("http://127.0.0.1:8765");
  const wsRef = useRef<WebSocket | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    window.neuronDesktop?.onConfig((c) => {
      if (c?.brain) setBrainBase(c.brain.replace(/\/$/, ""));
    });
  }, []);

  useEffect(() => {
    const host = brainBase.replace(/^https?:\/\//, "");
    const ws = new WebSocket(`ws://${host}/ws`);
    wsRef.current = ws;
    ws.onopen = () => {
      setBrain("BRAIN: ONLINE");
      setStatus("LOADING WHISPER...");
    };
    ws.onclose = () => {
      setBrain("BRAIN: OFFLINE");
      setStatus("RECONNECTING...");
      setTimeout(() => setBrainBase((b) => b + ""), 1500);
    };
    ws.onmessage = (ev) => {
      let msg: WsMsg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === "stt_status") {
        if (msg.ready) setStatus(`LISTENING (${(msg.backend || msg.engine || "whisper").toUpperCase()})`);
        else if (msg.error) setStatus("WHISPER FAILED");
        else setStatus("LOADING WHISPER...");
      }
      if (msg.type === "hearing") setStatus("HEARING YOU...");
      if (msg.type === "heard" && msg.text) {
        setHeard(msg.text);
        setStatus("WORKING...");
      }
      if (msg.type === "confirm") {
        setHeard(msg.heard || "");
        setReply(msg.text || msg.reason || "Confirm?");
        setStatus("CONFIRM REQUIRED");
      }
      if (msg.type === "response") {
        if (msg.heard) setHeard(msg.heard);
        if (msg.text) {
          setReply(msg.text);
          if (msg.audio_url) {
            const url = `${brainBase}${msg.audio_url}`;
            if (!audioRef.current) audioRef.current = new Audio();
            try {
              audioRef.current.pause();
            } catch {
              /* ignore */
            }
            audioRef.current.src = url;
            audioRef.current.play().catch(() => speakBrowser(msg.text || ""));
          } else {
            speakBrowser(msg.text);
          }
        }
        setStatus("LISTENING");
      }
      if (msg.type === "stop_speech") {
        window.speechSynthesis?.cancel();
        if (audioRef.current) {
          try {
            audioRef.current.pause();
            audioRef.current.currentTime = 0;
            audioRef.current.removeAttribute("src");
            audioRef.current.load();
          } catch {
            /* ignore */
          }
        }
        setReply(msg.text || "Okay.");
        setStatus("LISTENING");
      }
    };
    return () => ws.close();
  }, [brainBase]);

  return (
    <div className="shell">
      <header>
        <h1>N.E.U.R.O.N</h1>
        <span className={brain.includes("ONLINE") ? "on" : "off"}>{brain}</span>
      </header>
      <main>
        <div className="core" />
        <div className="status">{status}</div>
      </main>
      <footer>
        <div className="reply">{reply || "\u00a0"}</div>
        <div className="label">AUDIO INPUT</div>
        <div className="heard">{heard || "\u00a0"}</div>
      </footer>
    </div>
  );
}

function speakBrowser(text: string) {
  if (!window.speechSynthesis || !text) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 1.15;
  u.pitch = 0.85;
  window.speechSynthesis.speak(u);
}
