'use client';

/**
 * The assistant: a button that floats over every screen and opens a chat.
 *
 * It answers from the operator's own data through read-only tools on the
 * server (ADR-064). Two things are always on show, because the request was
 * "no data leak": where a question goes, and under each answer exactly which
 * data was sent to produce it.
 */

import { useEffect, useRef, useState } from 'react';
import {
  assistantChat,
  assistantStatus,
  type AssistantStatus,
  type AssistantTurn,
  type AssistantUse,
} from '@/lib/api';
import './assistant.css';

type Entry = AssistantTurn & { used?: AssistantUse[]; failed?: boolean };

const STARTERS = [
  'How are my paper deployments doing?',
  'Which datasets are behind?',
  'What did the Nifty gap study find?',
  'What orders did deployment 1 place last?',
];

const STORE = 'eulerlab.assistant.thread';

function loadThread(): Entry[] {
  try {
    const raw = window.sessionStorage.getItem(STORE);
    return raw ? (JSON.parse(raw) as Entry[]) : [];
  } catch {
    return [];
  }
}

export default function Assistant() {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<AssistantStatus | null>(null);
  const [thread, setThread] = useState<Entry[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [showTools, setShowTools] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => setThread(loadThread()), []);

  useEffect(() => {
    try {
      window.sessionStorage.setItem(STORE, JSON.stringify(thread.slice(-40)));
    } catch {
      /* private window: the chat still works, it is just not kept */
    }
    end.current?.scrollIntoView({ block: 'end' });
  }, [thread, busy]);

  useEffect(() => {
    if (!open) return;
    assistantStatus()
      .then(setStatus)
      .catch(() => setStatus({ ready: false, reason: 'The API is not running.', tools: [] }));
    input.current?.focus();
  }, [open]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  async function send(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    const next: Entry[] = [...thread, { role: 'user', content: question }];
    setThread(next);
    setDraft('');
    setBusy(true);
    try {
      const reply = await assistantChat(
        next.filter((e) => !e.failed).map(({ role, content }) => ({ role, content })),
      );
      setThread([
        ...next,
        reply.ok
          ? { role: 'assistant', content: reply.text, used: reply.used }
          : { role: 'assistant', content: reply.error, failed: true },
      ]);
    } catch (error) {
      setThread([...next, { role: 'assistant', content: String(error), failed: true }]);
    } finally {
      setBusy(false);
      input.current?.focus();
    }
  }

  const where = !status
    ? 'Checking…'
    : !status.ready
      ? 'Off'
      : status.local
        ? `Local model · ${status.model}`
        : `${status.host} · ${status.model}`;

  return (
    <>
      <button
        type="button"
        className={`asst-fab${open ? ' is-open' : ''}`}
        aria-label={open ? 'Close the assistant' : 'Open the assistant'}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? (
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M5 5h14v10H10l-5 4z" />
            <path d="M9 9h6M9 12h4" />
          </svg>
        )}
      </button>

      {open && (
        <section className="asst-panel" role="dialog" aria-label="Assistant">
          <header className="asst-head">
            <div>
              <strong>Assistant</strong>
              <span className={`asst-where${status && !status.ready ? ' is-off' : ''}`}>
                {where}
              </span>
            </div>
            <div className="asst-head-actions">
              <button type="button" onClick={() => setShowTools((v) => !v)}>
                {showTools ? 'Chat' : 'What it can read'}
              </button>
              {thread.length > 0 && (
                <button type="button" onClick={() => setThread([])}>
                  Clear
                </button>
              )}
            </div>
          </header>

          {showTools ? (
            <div className="asst-body">
              <p className="asst-note">
                It can only read, through these tools. It cannot place orders, run backtests or see
                your keys. Only your question and the tool answers it asks for are sent.
              </p>
              <ul className="asst-tools">
                {(status?.tools ?? []).map((tool) => (
                  <li key={tool.name}>
                    <code>{tool.name}</code>
                    <span>{tool.description}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="asst-body" aria-live="polite">
              {status && !status.ready && <p className="asst-off">{status.reason}</p>}
              {thread.length === 0 && status?.ready && (
                <div className="asst-starters">
                  <p className="asst-note">Ask about your data, strategies, research or trades.</p>
                  {STARTERS.map((text) => (
                    <button key={text} type="button" onClick={() => send(text)}>
                      {text}
                    </button>
                  ))}
                </div>
              )}
              {thread.map((entry, index) => (
                <div
                  key={index}
                  className={`asst-msg is-${entry.role}${entry.failed ? ' is-failed' : ''}`}
                >
                  <p>{entry.content}</p>
                  {entry.role === 'assistant' && !entry.failed && (
                    <small>
                      {entry.used && entry.used.length > 0
                        ? `Sent: ${entry.used
                            .map((u) => `${u.tool} (${u.characters.toLocaleString()} chars)`)
                            .join(', ')}`
                        : 'Sent: your question only'}
                    </small>
                  )}
                </div>
              ))}
              {busy && <div className="asst-msg is-assistant is-waiting">Looking it up…</div>}
              <div ref={end} />
            </div>
          )}

          <form
            className="asst-form"
            onSubmit={(event) => {
              event.preventDefault();
              void send(draft);
            }}
          >
            <textarea
              ref={input}
              value={draft}
              rows={2}
              maxLength={2000}
              placeholder={status?.ready === false ? 'The assistant is off' : 'Ask a question'}
              disabled={busy || status?.ready === false}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  void send(draft);
                }
              }}
            />
            <button type="submit" disabled={busy || !draft.trim() || status?.ready === false}>
              Send
            </button>
          </form>
        </section>
      )}
    </>
  );
}
