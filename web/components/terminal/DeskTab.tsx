/**
 * The trade desk (ADR-087): one ticket per live deployment, one row each
 * (ADR-207); a row opens to its orders, failing checks and decision.
 *
 * Each ticket shows what the book will sell and buy at its next rebalance, an
 * estimated cost, why, and the pre-trade checks. A paper ticket's decision is
 * a record only. A live deployment (not enabled yet) will not send a day's
 * orders until that day's ticket is approved here, and a blocked ticket
 * cannot be approved.
 */

'use client';

import { useCallback, useEffect, useState } from 'react';

import { agentsApi } from '@/lib/api';
import type { DeskTicket } from '@/lib/api';

function rupees(value: number): string {
  return `₹${value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
}

const sum = (values: number[]) => values.reduce((a, b) => a + b, 0);

/**
 * One ticket as one row; its orders, checks and decision open beneath it.
 * Only the failing checks are listed; the passing ones are counted.
 */
function TicketRow({
  ticket,
  title,
  open,
  onToggle,
  onDone,
}: {
  ticket: DeskTicket;
  title: string;
  open: boolean;
  onToggle: () => void;
  onDone: () => void;
}) {
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const decide = (decision: 'approved' | 'rejected') =>
    agentsApi
      .decideTicket(ticket.id, decision, note)
      .then((r) => {
        setError(r.ok ? '' : r.error ?? 'not recorded');
        onDone();
      })
      .catch((e: unknown) => setError(String(e)));
  const failing = ticket.checks.filter((c) => !c.ok);
  const sold = sum(ticket.sells.map((x) => x.value));
  const bought = sum(ticket.buys.map((x) => x.target_value));
  const trades = ticket.sells.length + ticket.buys.length;
  const status = ticket.decision
    ? { tone: ticket.decision === 'approved' ? 'up' : '', text: ticket.decision }
    : ticket.blocked
      ? { tone: 'down', text: `blocked: ${failing[0]?.name ?? 'check'}` }
      : { tone: 'brand', text: 'ready' };
  return (
    <>
      <tr className="desk-row" onClick={onToggle} aria-expanded={open}>
        <td>
          <span className="desk-caret">{open ? '▾' : '▸'}</span>
          <b title={ticket.deployment}>{title}</b>
          {ticket.mode !== 'paper' && <span className="tbadge" data-tone="caveat">{ticket.mode}</span>}
        </td>
        <td className="r">{rupees(ticket.equity)}</td>
        <td>
          {trades === 0 ? (
            <span className="tdim">no trades</span>
          ) : (
            <>
              {ticket.sells.length > 0 && <span className="neg">{ticket.sells.length} sell {rupees(sold)}</span>}
              {ticket.sells.length > 0 && ticket.buys.length > 0 && ' · '}
              {ticket.buys.length > 0 && <span className="pos">{ticket.buys.length} buy {rupees(bought)}</span>}
            </>
          )}
        </td>
        <td className="r">{rupees(ticket.est_cost)}</td>
        <td className="tfine">{ticket.rebalance || '—'}</td>
        <td className="r">
          <span className="tbadge" data-tone={status.tone} title={failing.map((c) => `${c.name}: ${c.detail}`).join('\n')}>
            {status.text}
          </span>
        </td>
      </tr>
      {open && (
        <tr className="desk-detail">
          <td colSpan={6}>
            <div className="desk-orders">
              {ticket.sells.map((x) => (
                <span key={`s-${x.symbol}`} className="desk-order neg">
                  Sell <b>{x.symbol}</b> {x.quantity} · {rupees(x.value)}
                </span>
              ))}
              {ticket.buys.map((x) => (
                <span key={`b-${x.symbol}`} className="desk-order pos">
                  Buy <b>{x.symbol}</b> {rupees(x.target_value)}
                </span>
              ))}
              {ticket.holds.length > 0 && (
                <span className="tfine" title={ticket.holds.join(', ')}>
                  {ticket.holds.length} kept
                </span>
              )}
            </div>
            <div className="tfine desk-checks">
              {failing.map((c) => (
                <div key={c.name} className="neg">
                  ✕ {c.name}: {c.detail}
                </div>
              ))}
              <span title={ticket.checks.filter((c) => c.ok).map((c) => `${c.name}: ${c.detail}`).join('\n')}>
                ✓ {ticket.checks.length - failing.length} of {ticket.checks.length} checks pass
              </span>
            </div>
            {error && <div className="tnote bad">{error}</div>}
            {!ticket.decision && (
              <div className="desk-decide">
                <input
                  className="tinput sm"
                  aria-label="note"
                  placeholder="note (optional)"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
                <button type="button" className="tbtn sm go" disabled={ticket.blocked} onClick={() => decide('approved')}>
                  Approve
                </button>
                <button type="button" className="tbtn sm" onClick={() => decide('rejected')}>
                  Reject
                </button>
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

export function DeskTab({ titles = {} }: { titles?: Record<string, string> }) {
  const [tickets, setTickets] = useState<DeskTicket[] | null>(null);
  const [error, setError] = useState('');
  const [open, setOpen] = useState('');
  const read = useCallback(() => {
    agentsApi
      .tickets()
      .then((r) => {
        // Live books only (operator, 2026-11-16): a paper ticket's decision is a
        // record only, so paper books are not shown here.
        setTickets(r.tickets.filter((t) => t.mode !== 'paper'));
        setError(r.ok ? '' : r.error ?? '');
      })
      .catch((e: unknown) => setError(String(e)));
  }, []);
  useEffect(() => {
    read();
  }, [read]);
  return (
    <div className="tpanel desk">
      <h3>
        Live books: next rebalance{' '}
        <span className="tfine">a live book sends nothing until its ticket is approved</span>
      </h3>
      {error && <div className="tnote bad">{error}</div>}
      {tickets === null ? (
        <div className="tempty">Reading tickets…</div>
      ) : tickets.length === 0 ? (
        <div className="tempty">No live book is running, so nothing waits for approval. Paper books trade on their own.</div>
      ) : (
        <table className="ttable desk-table">
          <thead>
            <tr>
              <th>Book</th>
              <th className="r">Equity</th>
              <th>Orders</th>
              <th className="r">Est. cost</th>
              <th>Rebalance</th>
              <th className="r">Status</th>
            </tr>
          </thead>
          <tbody>
            {tickets.map((t) => (
              <TicketRow
                key={t.id}
                ticket={t}
                title={titles[t.strategy] ?? t.strategy}
                open={open === t.id}
                onToggle={() => setOpen(open === t.id ? '' : t.id)}
                onDone={read}
              />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
