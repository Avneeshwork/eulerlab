'use client';

/**
 * Log in (ADR-168). Shown only when the server runs with EULERLAB_AUTH=on;
 * every API helper sends a 401 here, and a successful login returns to the
 * page that asked. The session is an HttpOnly cookie the browser keeps.
 */

import { useState } from 'react';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { detail?: string };
        setError(body.detail ?? `login failed (${response.status})`);
        return;
      }
      const next = new URLSearchParams(window.location.search).get('next') ?? '/';
      window.location.assign(next.startsWith('/') && !next.startsWith('//') ? next : '/');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main style={{ maxWidth: 360, margin: '15vh auto', padding: '0 16px', fontFamily: 'inherit' }}>
      <h1 style={{ fontSize: 22, marginBottom: 16 }}>EulerLab</h1>
      <form onSubmit={submit} style={{ display: 'grid', gap: 12 }}>
        <label style={{ display: 'grid', gap: 4 }}>
          Email
          <input
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label style={{ display: 'grid', gap: 4 }}>
          Password
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? 'Logging in…' : 'Log in'}
        </button>
        {error && <p role="alert">{error}</p>}
      </form>
    </main>
  );
}
