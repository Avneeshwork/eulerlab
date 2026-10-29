/**
 * The trade desk (ADR-087): one ticket per active deployment.
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

function TicketCard({ ticket, onDone }: { ticket: DeskTicket; onDone: () => void }) {
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
  return (
    <div className="tpanel" style={{ padding: 16 }}>
      <h3>
        {ticket.deployment} <span className="tchip">{ticket.mode}</span>{' '}
        {ticket.decision ? <span className="tchip">{ticket.decision}</span> : ticket.blocked ? <span className="tchip">blocked</span> : null}
      </h3>
      <p className="tdesc">{ticket.reason}</p>
      <p className="tfine">
        Equity {rupees(ticket.equity)} · estimated cost {rupees(ticket.est_cost)} · {ticket.holds.length} names kept
      </p>
      <table className="ttable">
        <thead>
          <tr>
            <th>Side</th>
            <th>Symbol</th>
            <th style={{ textAlign: 'right' }}>Quantity</th>
            <th style={{ textAlign: 'right' }}>Value</th>
          </tr>
        </thead>
        <tbody>
          {ticket.sells.map((s) => (
            <tr key={`s-${s.symbol}`}>
              <td>Sell</td>
              <td>{s.symbol}</td>
              <td style={{ textAlign: 'right' }}>{s.quantity}</td>
              <td style={{ textAlign: 'right' }}>{rupees(s.value)}</td>
            </tr>
          ))}
          {ticket.buys.map((b) => (
            <tr key={`b-${b.symbol}`}>
              <td>Buy</td>
              <td>{b.symbol}</td>
              <td style={{ textAlign: 'right' }} className="tfine">
                set at fill
              </td>
              <td style={{ textAlign: 'right' }}>{rupees(b.target_value)}</td>
            </tr>
          ))}
          {ticket.sells.length + ticket.buys.length === 0 && (
            <tr>
              <td colSpan={4} className="tfine">
                No trades: the book already holds what it wants.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <h3 style={{ marginTop: 12 }}>Checks</h3>
      <table className="ttable">
        <tbody>
          {ticket.checks.map((c) => (
            <tr key={c.name}>
              <td>{c.ok ? 'pass' : <b>block</b>}</td>
              <td>{c.name}</td>
              <td className="tfine">{c.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {error && <p className="tnote bad">{error}</p>}
      {!ticket.decision && (
        <div style={{ marginTop: 8 }}>
          <input
            aria-label="note"
            placeholder="note (optional)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            style={{ width: 260, font: 'inherit' }}
          />{' '}
          <button type="button" className="tbtn sm go" disabled={ticket.blocked} onClick={() => decide('approved')}>
            Approve
          </button>{' '}
          <button type="button" className="tbtn sm" onClick={() => decide('rejected')}>
            Reject
          </button>
        </div>
      )}
    </div>
  );
}

export function DeskTab() {
  const [tickets, setTickets] = useState<DeskTicket[] | null>(null);
  const [error, setError] = useState('');
  const read = useCallback(() => {
    agentsApi
      .tickets()
      .then((r) => {
        setTickets(r.tickets);
        setError(r.ok ? '' : r.error ?? '');
      })
      .catch((e: unknown) => setError(String(e)));
  }, []);
  useEffect(() => {
    read();
  }, [read]);
  return (
    <section className="tsection" style={{ display: 'grid', gap: 16 }}>
      <p className="tfine">
        A paper ticket&rsquo;s decision is a record only; paper books keep trading on their own. A live
        book will not send a day&rsquo;s orders until that day&rsquo;s ticket is approved, and a blocked
        ticket cannot be approved.
      </p>
      {error && <p className="tnote bad">{error}</p>}
      {tickets === null ? null : tickets.length === 0 ? (
        <div className="tempty">No active deployments, so no tickets.</div>
      ) : (
        tickets.map((t) => <TicketCard key={t.id} ticket={t} onDone={read} />)
      )}
    </section>
  );
}
