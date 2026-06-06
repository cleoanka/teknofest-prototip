/**
 * Yeniden bağlanan WebSocket hook'ları.
 * - useSocket: genel amaçlı (exponential backoff + AppState yönetimi)
 * - useFrameSocket: /ws/ingest — kare gönder, FrameResult al
 * - useStatusSocket: /ws/status — 1 sn'lik sistem durumu yayınını dinle
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState, AppStateStatus } from "react-native";
import { wsUrl } from "./client";
import type { FrameResult, StatusFrame } from "../types/api";

export type SocketStatus = "connecting" | "connected" | "reconnecting" | "disconnected";

interface UseSocketOpts {
  path: string;
  onMessage: (data: any) => void;
  enabled?: boolean;
}

function useSocket({ path, onMessage, enabled = true }: UseSocketOpts) {
  const [status, setStatus] = useState<SocketStatus>("connecting");
  const wsRef = useRef<WebSocket | null>(null);
  const retry = useRef(0);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(true);
  const appState = useRef<AppStateStatus>(AppState.currentState);
  const onMsg = useRef(onMessage);
  onMsg.current = onMessage;

  const clearRetry = () => {
    if (retryTimer.current) { clearTimeout(retryTimer.current); retryTimer.current = null; }
  };
  const backoff = (n: number) => Math.min(1000 * 2 ** n, 30_000);

  const connect = useCallback(() => {
    if (!mounted.current || !enabled) return;
    let ws: WebSocket;
    try {
      ws = new WebSocket(wsUrl(path));
    } catch {
      setStatus("disconnected");
      return;
    }
    wsRef.current = ws;
    setStatus(retry.current > 0 ? "reconnecting" : "connecting");

    ws.onopen = () => {
      if (!mounted.current) { ws.close(); return; }
      retry.current = 0;
      setStatus("connected");
    };
    ws.onclose = () => {
      if (!mounted.current) return;
      wsRef.current = null;
      setStatus("disconnected");
      if (appState.current === "active" && enabled) {
        const d = backoff(retry.current++);
        retryTimer.current = setTimeout(connect, d);
      }
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (!data?.error) onMsg.current(data);
      } catch {}
    };
  }, [path, enabled]);

  const disconnect = useCallback(() => {
    clearRetry();
    const ws = wsRef.current;
    wsRef.current = null;
    ws?.close();
  }, []);

  const send = useCallback((payload: string) => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) ws.send(payload);
  }, []);

  useEffect(() => {
    mounted.current = true;
    if (!enabled) { setStatus("disconnected"); return; }
    connect();

    const sub = AppState.addEventListener("change", (next) => {
      const prev = appState.current;
      appState.current = next;
      if (next === "active" && prev !== "active") {
        disconnect(); retry.current = 0; connect();
      } else if (next !== "active" && prev === "active") {
        disconnect(); setStatus("disconnected");
      }
    });

    return () => {
      mounted.current = false;
      sub.remove();
      disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, path]);

  return { status, send };
}

/** /ws/ingest — kameradan kare gönder, işlenmiş FrameResult al. */
export function useFrameSocket(onFrame: (f: FrameResult) => void, enabled = true) {
  return useSocket({ path: "/ws/ingest", onMessage: onFrame, enabled });
}

/** /ws/status — sistem durumu yayınını dinle (saniyede bir). */
export function useStatusSocket(onStatus: (s: StatusFrame) => void, enabled = true) {
  const { status } = useSocket({ path: "/ws/status", onMessage: onStatus, enabled });
  return { status };
}
