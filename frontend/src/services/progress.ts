import { useEffect, useState } from 'react';
import { api } from './api';
import type { ProgressSnapshot } from '../types/api';

/** Random id the backend uses to report the real stages of one heavy request (letters, digits, `-`, `_`; 16-64). */
export function newProgressId(): string {
  const c = globalThis.crypto;
  if (c?.randomUUID) return c.randomUUID().replace(/-/g, '');
  const bytes = new Uint8Array(16);
  if (c?.getRandomValues) c.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Polls the backend for the real processing stages while `active`. Errors are ignored on purpose: with several
 * server instances a poll can reach one that knows nothing about this request, and then no detail is shown.
 */
export function useProgress(id: string | null, active: boolean, intervalMs = 4000): ProgressSnapshot | null {
  const [snapshot, setSnapshot] = useState<ProgressSnapshot | null>(null);
  useEffect(() => {
    if (!active || !id) { setSnapshot(null); return undefined; }
    let stopped = false;
    const tick = async () => {
      try {
        const s = await api.progress(id);
        if (!stopped) setSnapshot(s);
      } catch { /* unknown on this instance: keep the last known state */ }
    };
    const first = window.setTimeout(tick, 1500);
    const timer = window.setInterval(tick, intervalMs);
    return () => { stopped = true; window.clearTimeout(first); window.clearInterval(timer); };
  }, [id, active, intervalMs]);
  return snapshot;
}
