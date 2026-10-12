'use client';

/**
 * Log in to Kite from the Instruments page.
 *
 * India's minute bars need a Kite token minted the same day, and the only way
 * to mint one was `make kite-login` in a terminal. Zerodha requires the account
 * holder to sign in on its own page, so this cannot be one click: it is a link
 * to that page, and a box for the address Zerodha sends the browser to after.
 */

import { useCallback, useEffect, useState } from 'react';
import { kiteLogin, kiteStatus, type KiteStatus } from '@/lib/api';

function clock(iso: string): string {
  const when = new Date(iso);
  return Number.isNaN(when.getTime())
    ? iso
    : when.toLocaleString('en-IN', {
        day: 'numeric',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      });
}

export function KiteLogin({ onLogin }: { onLogin: () => void }) {
  const [status, setStatus] = useState<KiteStatus | null>(null);
  const [pasted, setPasted] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const read = useCallback(() => {
    kiteStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);
  useEffect(read, [read]);

  async function submit() {
    if (!pasted.trim() || busy) return;
    setBusy(true);
    setError('');
    try {
      const reply = await kiteLogin(pasted.trim());
      if (reply.ok) {
        setPasted('');
        read();
        onLogin();
      } else {
        setError(reply.error);
      }
    } catch (problem) {
      setError(String(problem));
    } finally {
      setBusy(false);
    }
  }

  if (!status) return null;

  return (
    <section className="tpanel kite-box">
      <div className="kite-head">
        <b>Kite (Zerodha)</b>
        <span className={`kite-state${status.fresh ? ' is-on' : ''}`}>
          {status.fresh
            ? `Logged in as ${status.user}, until ${clock(status.expires_at ?? '')}`
            : status.configured
              ? 'Not logged in today'
              : 'Not set up'}
        </span>
      </div>
      {!status.configured && <p className="tfine">{status.reason}.</p>}
      {status.configured && !status.fresh && (
        <>
          <p className="tfine">
            India minute bars need a Kite token made today; it expires at 06:00 IST. Zerodha asks
            you to sign in on its own page:
          </p>
          <ol className="kite-steps">
            <li>
              <a href={status.login_url} target="_blank" rel="noreferrer noopener">
                Open Zerodha&apos;s login page
              </a>{' '}
              and sign in.
            </li>
            <li>
              Zerodha then sends the browser to another address. Copy that whole address from the
              address bar and paste it here.
            </li>
          </ol>
          <form
            className="kite-form"
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <input
              value={pasted}
              aria-label="The address Zerodha redirected to"
              placeholder="https://…?request_token=…"
              autoComplete="off"
              spellCheck={false}
              onChange={(event) => setPasted(event.target.value)}
            />
            <button type="submit" className="tbtn" disabled={busy || !pasted.trim()}>
              {busy ? 'Logging in…' : 'Log in'}
            </button>
          </form>
          {error && <p className="kite-error">{error}</p>}
        </>
      )}
      {status.fresh && (
        <p className="tfine">
          The India minute bars row below can now be updated with its own button.
        </p>
      )}
    </section>
  );
}
