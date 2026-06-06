import { useCallback, useEffect, useRef, useState } from "react";
import { AppState, AppStateStatus } from "react-native";
import { getWsIngest } from "../api/client";

export type WsStatus = "connecting" | "connected" | "disconnected" | "reconnecting";

interface UseWebSocketOptions {
  onMessage: (data: any) => void;
  /** true olduğunda WS bağlantısı kurulmaz; status hemen "connected" döner (mock mod için) */
  disabled?: boolean;
}

export function useWebSocket({ onMessage, disabled = false }: UseWebSocketOptions) {
  const [status, setStatus] = useState<WsStatus>("connecting");
  const wsRef = useRef<WebSocket | null>(null);
  const retryCount = useRef(0);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isMounted = useRef(true);
  const appState = useRef<AppStateStatus>(AppState.currentState);
  // onMessage referansını stale closure'dan korumak için
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  const clearRetryTimer = () => {
    if (retryTimer.current) {
      clearTimeout(retryTimer.current);
      retryTimer.current = null;
    }
  };

  // Her denemede bekleme süresi: 1s, 2s, 4s, 8s, 16s, 30s (max)
  const getDelay = (attempt: number) => Math.min(1000 * Math.pow(2, attempt), 30_000);

  const connect = useCallback(() => {
    if (!isMounted.current) return;

    const ws = new WebSocket(getWsIngest());
    wsRef.current = ws;
    setStatus(retryCount.current > 0 ? "reconnecting" : "connecting");

    ws.onopen = () => {
      if (!isMounted.current) { ws.close(); return; }
      retryCount.current = 0;
      setStatus("connected");
    };

    ws.onclose = () => {
      if (!isMounted.current) return;
      wsRef.current = null;
      setStatus("disconnected");
      // Uygulama öndeyse yeniden bağlan
      if (appState.current === "active") {
        const delay = getDelay(retryCount.current);
        retryCount.current += 1;
        retryTimer.current = setTimeout(connect, delay);
      }
    };

    ws.onerror = () => {
      ws.close(); // onclose tetiklenir, oradan retry devreye girer
    };

    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (!data.error) onMessageRef.current(data);
      } catch {}
    };
  }, []);

  const disconnect = useCallback(() => {
    clearRetryTimer();
    const ws = wsRef.current;
    wsRef.current = null;
    ws?.close();
  }, []);

  const send = useCallback((payload: string) => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) ws.send(payload);
  }, []);

  useEffect(() => {
    if (disabled) { setStatus("connected"); return; }
    isMounted.current = true;
    connect();

    const sub = AppState.addEventListener("change", (next: AppStateStatus) => {
      const prev = appState.current;
      appState.current = next;

      if (next === "active" && prev !== "active") {
        // Ön plana döndü — sıfırdan bağlan
        disconnect();
        retryCount.current = 0;
        connect();
      } else if (next !== "active" && prev === "active") {
        // Arka plana geçti — bağlantıyı kapat, retry zamanlayıcısını durdur
        disconnect();
        setStatus("disconnected");
      }
    });

    return () => {
      isMounted.current = false;
      sub.remove();
      disconnect();
    };
  }, []);

  return { status, wsRef, send };
}
