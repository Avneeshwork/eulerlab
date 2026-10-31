'use client';

/** Sign in to FYERS from Instruments, following the Kite login pattern. */

import { Info } from '@/components/terminal/ui';
import { useCallback, useEffect, useState } from 'react';
import { fyersLogin, fyersStatus, type FyersStatus } from '@/lib/api';

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

export function FyersLogin() {
  const [status, setStatus] = useState<FyersStatus | null>(null);
  const [pasted, setPasted] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const read = useCallback(() => {
    fyersStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);
  useEffect(read, [read]);

  async function submit() {
    if (!pasted.trim() || busy) return;
    setBusy(true);
    setError('');
    try {
      const reply = await fyersLogin(pasted.trim());
      if (reply.ok) {
        setPasted('');
        read();
      } else {
        setError(reply.error);
        read();
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
        <b>FYERS</b>
        <span className={`kite-state${status.fresh ? ' is-on' : ''}`}>
          {status.fresh
            ? `Logged in as ${status.user || 'user'}, until ${clock(status.expires_at ?? '')}`
            : status.configured
              ? 'Not logged in today'
              : 'Not set up'}
        </span>
      </div>
      {!status.configured && <p className="tfine">{status.reason}.</p>}
      {status.configured && !status.fresh && (
        <>
          <p className="tfine">
            FYERS access tokens expire daily. Sign in on FYERS, then paste the full redirect address
            here; the app secret and access token stay on this server.
          </p>
          <ol className="kite-steps">
            <li>
              <a href={status.login_url} target="_blank" rel="noreferrer noopener">
                Open FYERS&apos; login page
              </a>{' '}
              and complete sign-in.
            </li>
            <li>
              Copy the final address from the browser and paste it here. It must include
              <code>auth_code</code> and <code>state</code>.
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
              aria-label="The address FYERS redirected to"
              placeholder="https://…?auth_code=…&state=…"
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
          <span className="ui-chip up">Expired futures data ready to fetch</span>
          <Info>FYERS history is fetched by the fixed micro-05 research command.</Info>
        </p>
      )}
    </section>
  );
}
