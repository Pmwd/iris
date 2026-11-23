import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Turn, TurnEvent } from "../types";

const ACTIVE = new Set(["starting", "running", "canceling"]);

export function useTurnStream(
  turnId: string | null,
  initialStatus: string,
  onDone?: (turn: Turn | null) => void,
) {
  const [events, setEvents] = useState<TurnEvent[]>([]);
  const [status, setStatus] = useState(initialStatus);
  const eventsRef = useRef<TurnEvent[]>([]);
  const seenRef = useRef<Set<number>>(new Set());
  const doneRef = useRef(false);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    if (!turnId) {
      setEvents([]);
      setStatus(initialStatus);
      return;
    }
    let cancelled = false;
    let source: EventSource | null = null;
    let interval: number | undefined;
    eventsRef.current = [];
    seenRef.current = new Set();
    doneRef.current = false;
    setEvents([]);
    setStatus(initialStatus);

    const apply = (incoming: TurnEvent[]) => {
      for (const event of incoming) {
        if (seenRef.current.has(event.seq)) continue;
        seenRef.current.add(event.seq);
        eventsRef.current.push(event);
      }
      eventsRef.current.sort((a, b) => a.seq - b.seq);
      setEvents([...eventsRef.current]);
    };

    const lastSeq = () =>
      eventsRef.current.length
        ? eventsRef.current[eventsRef.current.length - 1].seq
        : 0;

    const finish = (turn: Turn | null) => {
      if (doneRef.current) return;
      doneRef.current = true;
      source?.close();
      if (interval) window.clearInterval(interval);
      onDoneRef.current?.(turn);
    };

    const poll = async () => {
      try {
        const turn = await api.getTurn(turnId);
        if (cancelled) return;
        setStatus(turn.status);
        if (!ACTIVE.has(turn.status)) finish(turn);
      } catch {
        // transient network error; keep polling
      }
    };

    const openStream = () => {
      source = new EventSource(api.turnStreamUrl(turnId, lastSeq()));
      source.addEventListener("turn_event", (event) => {
        try {
          const data = JSON.parse((event as MessageEvent).data) as TurnEvent;
          apply([data]);
        } catch {
          // ignore malformed event
        }
      });
      source.addEventListener("done", () => {
        source?.close();
        void poll();
      });
      source.onerror = () => {
        // EventSource reconnects automatically; polling remains a fallback.
      };
    };

    void (async () => {
      try {
        const history = await api.listTurnEvents(turnId, 0);
        if (cancelled) return;
        apply(history);
        const turn = await api.getTurn(turnId);
        if (cancelled) return;
        setStatus(turn.status);
        if (ACTIVE.has(turn.status)) {
          openStream();
        } else {
          finish(turn);
        }
      } catch {
        // leave polling to surface the status
      }
    })();

    interval = window.setInterval(() => void poll(), 1500);

    return () => {
      cancelled = true;
      source?.close();
      if (interval) window.clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [turnId]);

  return { events, status };
}
