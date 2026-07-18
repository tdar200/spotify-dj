"use client";

import { useCallback, useEffect, useState } from "react";
import FeedbackButtons from "./FeedbackButtons";

const API = "http://127.0.0.1:8765";

type Item = {
  track_id: string;
  name: string;
  artist: string;
  score: number;
  why: string[];
};

export default function Discover() {
  const [items, setItems] = useState<Item[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    fetch(`${API}/discover?limit=30`)
      .then((r) => r.json())
      .then((d) => setItems(d.items))
      .catch(() => setNotice("Backend not reachable on :8765 — is it running?"));
  }, []);

  useEffect(load, [load]);

  const refresh = async () => {
    setBusy("Refreshing candidates — this hits Last.fm/ListenBrainz and can take a minute…");
    try {
      const r = await fetch(`${API}/discover/refresh`, { method: "POST" });
      if (!r.ok) throw new Error();
      const d = await r.json();
      setNotice(`${d.new} new candidates`);
      load();
    } catch {
      setNotice("Refresh failed — is Spotify connected?");
    } finally {
      setBusy(null);
    }
  };

  const sendFeedback = async (trackId: string, verdict: string) => {
    await fetch(`${API}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ track_id: trackId, verdict }),
    });
  };

  const queue = async (trackId: string) => {
    const r = await fetch(`${API}/playback/queue`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ track_id: trackId }),
    });
    setNotice(r.ok ? "Queued." : "Queue failed — is Spotify playing on a device?");
  };

  const toggle = (id: string) => {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const savePlaylist = async () => {
    const r = await fetch(`${API}/playlists/from-feed`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ track_ids: [...selected] }),
    });
    if (r.ok) {
      const d = await r.json();
      setNotice("Playlist created.");
      window.open(d.url, "_blank");
    } else {
      setNotice("Playlist failed — is Spotify connected?");
    }
  };

  return (
    <main className="mx-auto max-w-3xl p-8 space-y-6">
      <h1 className="text-2xl font-bold">Spotify DJ — Discover</h1>
      <p>
        <a href="/" className="text-sm underline">← Stats</a>
      </p>

      <div className="flex items-center gap-4">
        <button
          onClick={refresh}
          disabled={busy !== null}
          className="rounded bg-green-600 px-4 py-2 font-semibold text-white disabled:opacity-40"
        >
          Refresh candidates
        </button>
        {selected.size > 0 && (
          <button
            onClick={savePlaylist}
            className="rounded bg-blue-600 px-4 py-2 font-semibold text-white"
          >
            Save {selected.size} as playlist
          </button>
        )}
      </div>

      {busy && <p className="text-sm text-gray-500">{busy}</p>}
      {notice && <p className="text-sm">{notice}</p>}
      {items.length === 0 && !busy && (
        <p className="text-gray-500">
          No candidates yet — hit “Refresh candidates”.
        </p>
      )}

      <ul className="space-y-4">
        {items.map((it) => (
          <li key={it.track_id} className="rounded border p-3 space-y-1">
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={selected.has(it.track_id)}
                onChange={() => toggle(it.track_id)}
              />
              <span className="font-semibold">{it.name}</span>
              <span>— {it.artist}</span>
              <span className="text-xs text-gray-400">
                {it.score.toFixed(2)}
              </span>
            </div>
            <p className="text-sm text-gray-500">{it.why.join(" · ")}</p>
            <div className="flex items-center gap-3">
              <a
                className="text-sm underline"
                href={`https://open.spotify.com/track/${it.track_id}`}
                target="_blank"
              >
                Open in Spotify
              </a>
              <button className="text-sm underline" onClick={() => queue(it.track_id)}>
                Queue
              </button>
              <FeedbackButtons trackId={it.track_id} onFeedback={sendFeedback} />
            </div>
          </li>
        ))}
      </ul>
    </main>
  );
}
