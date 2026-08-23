// Live generation progress, polled from the backend.
//
// The bar used to be a `setInterval` creeping toward an arbitrary cap, which meant
// it said the same thing whether a render was healthy or wedged. The backend now
// reports which stage a job is in (and, while rendering, how many scenes are done),
// so this hook turns that into a percentage the UI can trust.
//
// Polling rather than SSE: the desktop build talks to a local server, the same
// jobId already keys `/jobs/cancel`, and a dropped tick costs nothing.
import { useEffect, useRef, useState } from "react";

import { apiFetch } from "@/lib/api";

export type JobStage = "planning" | "preparing" | "rendering" | "assembling";

export type JobProgress = {
  /** 0-100, monotonic. Null until the backend reports something. */
  percent: number | null;
  stage: JobStage | null;
  /** Scenes rendered / total, only meaningful during `rendering`. */
  done: number;
  total: number;
};

const EMPTY: JobProgress = { percent: null, stage: null, done: 0, total: 0 };

const POLL_MS = 1500;

// Share of the bar each stage owns. Rendering gets the bulk because it is both the
// longest phase and the only one that can report a real fraction.
const STAGE_FLOOR: Record<JobStage, number> = {
  planning: 8,
  preparing: 22,
  rendering: 25,
  assembling: 92,
};
const RENDERING_SPAN = 85 - STAGE_FLOOR.rendering;

function toPercent(stage: JobStage, done: number, total: number): number {
  if (stage === "rendering" && total > 0) {
    return STAGE_FLOOR.rendering + Math.round((RENDERING_SPAN * Math.min(done, total)) / total);
  }
  return STAGE_FLOOR[stage];
}

/**
 * Polls `/jobs/progress` while `active` is true.
 *
 * Returns `percent: null` when the backend has nothing to say — a job that has not
 * reported yet, a generation type that is not instrumented, or an older backend.
 * Callers should fall back to their own estimate in that case rather than showing
 * a bar stuck at zero.
 */
export function useJobProgress(jobId: string | null, active: boolean): JobProgress {
  const [progress, setProgress] = useState<JobProgress>(EMPTY);
  // Kept in a ref so the poll loop can enforce monotonicity without re-subscribing.
  const highWaterMark = useRef(0);

  useEffect(() => {
    if (!active || !jobId) {
      setProgress(EMPTY);
      highWaterMark.current = 0;
      return;
    }

    let cancelled = false;

    const poll = async () => {
      try {
        const response = await apiFetch(
          `/jobs/progress?jobId=${encodeURIComponent(jobId)}`
        );
        if (cancelled || !response.ok) return;

        const data = await response.json();
        if (cancelled || !data?.active) return;

        const stage = data.stage as JobStage;
        if (!(stage in STAGE_FLOOR)) return;

        const done = Number(data.done) || 0;
        const total = Number(data.total) || 0;
        // A repair pass can re-render a scene, so the raw count can dip. The bar
        // going backwards reads as a failure, so only ever move forward.
        const next = Math.max(highWaterMark.current, toPercent(stage, done, total));
        highWaterMark.current = next;
        setProgress({ percent: next, stage, done, total });
      } catch {
        // Backend not up yet, or the request raced a shutdown. Keep the last value.
      }
    };

    void poll();
    const timer = window.setInterval(() => void poll(), POLL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [jobId, active]);

  return progress;
}
