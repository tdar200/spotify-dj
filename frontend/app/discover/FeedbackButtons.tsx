"use client";

import { useState } from "react";

type Verdict = "up" | "down" | "more_like_this";

export default function FeedbackButtons({
  trackId,
  onFeedback,
}: {
  trackId: string;
  onFeedback: (trackId: string, verdict: Verdict) => Promise<void>;
}) {
  const [sent, setSent] = useState<Verdict | null>(null);

  const send = (verdict: Verdict) => {
    setSent(verdict);
    onFeedback(trackId, verdict).catch(() => setSent(null));
  };

  const btn = "rounded border px-2 py-1 text-sm disabled:opacity-40";
  return (
    <span className="space-x-2">
      <button className={btn} disabled={sent !== null} onClick={() => send("up")}>
        👍
      </button>
      <button className={btn} disabled={sent !== null} onClick={() => send("down")}>
        👎
      </button>
      <button
        className={btn}
        disabled={sent !== null}
        onClick={() => send("more_like_this")}
      >
        More like this
      </button>
    </span>
  );
}
