"use client";

import { useEffect, useState } from "react";

const API = "http://127.0.0.1:8765";

type Play = { played_at: string; track: string; artist: string };
type TopTrack = { name: string; artist: string; plays: number };
type TopArtist = { name: string; plays: number };

export default function Home() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [recent, setRecent] = useState<Play[]>([]);
  const [topTracks, setTopTracks] = useState<TopTrack[]>([]);
  const [topArtists, setTopArtists] = useState<TopArtist[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/auth/status`)
      .then((r) => r.json())
      .then((d) => setConnected(d.connected))
      .catch(() => setError("Backend not reachable on :8765 — is it running?"));
    fetch(`${API}/stats/recent`)
      .then((r) => r.json())
      .then(setRecent)
      .catch(() => {});
    fetch(`${API}/stats/top`)
      .then((r) => r.json())
      .then((d) => {
        setTopTracks(d.tracks);
        setTopArtists(d.artists);
      })
      .catch(() => {});
  }, []);

  return (
    <main className="mx-auto max-w-3xl p-8 space-y-8">
      <h1 className="text-2xl font-bold">Spotify DJ — Stats</h1>

      {error && <p className="text-red-500">{error}</p>}

      {connected === false && (
        <a
          href={`${API}/auth/login`}
          className="inline-block rounded bg-green-600 px-4 py-2 font-semibold text-white"
        >
          Connect Spotify
        </a>
      )}

      {connected && (
        <p className="text-sm text-green-600">
          Spotify connected — logging your listening history.
        </p>
      )}

      <section>
        <h2 className="mb-2 text-lg font-semibold">Top artists (30 days)</h2>
        <ol className="list-decimal pl-6">
          {topArtists.map((a) => (
            <li key={a.name}>
              {a.name} <span className="text-gray-500">({a.plays} plays)</span>
            </li>
          ))}
        </ol>
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Top tracks (30 days)</h2>
        <ol className="list-decimal pl-6">
          {topTracks.map((t) => (
            <li key={`${t.name}-${t.artist}`}>
              {t.name} — {t.artist}{" "}
              <span className="text-gray-500">({t.plays} plays)</span>
            </li>
          ))}
        </ol>
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Recent plays</h2>
        <ul className="space-y-1">
          {recent.map((p) => (
            <li key={p.played_at} className="text-sm">
              <span className="text-gray-500">
                {new Date(p.played_at).toLocaleString()}
              </span>{" "}
              — {p.track} — {p.artist}
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
