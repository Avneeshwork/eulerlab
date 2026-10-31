/**
 * The market brief, drawn from its data (ADR-105, research 134).
 *
 * In the order a trader reads it: the headline with its tone, the three things
 * that matter today (fact, then what it means), levels and what would change
 * the read, what is coming up, what in the books needs you, then the
 * scorecard, what is moving underneath and the raw detail, folded away.
 * After the close it opens with this morning's read against the close.
 *
 * `BriefCard` is the short form for the agent strip: headline, the three
 * titles and a link to the whole brief.
 */

'use client';

import type { MarketBrief } from '@/lib/api';
import './marketbrief.css';

const TONE_WORD: Record<MarketBrief['tone'], string> = {
  weak: 'Leaning weak',
  supportive: 'Leaning supportive',
  mixed: 'Mixed',
  incomplete: 'Incomplete',
};

const WORD_MARK: Record<string, string> = { supportive: '+', neutral: '=', weak: '−', missing: '?' };

function Section({ title, children, open = true }: { title: string; children: React.ReactNode; open?: boolean }) {
  return (
    <details className="mb-sec" open={open}>
      <summary>{title}</summary>
      <div className="mb-sec-body">{children}</div>
    </details>
  );
}

export function BriefCard({ brief, onOpen }: { brief: MarketBrief; onOpen: () => void }) {
  return (
    <div className="mb-card" data-tone={brief.tone}>
      <p className="mb-card-head">{brief.headline}</p>
      {brief.matters.length > 0 && (
        <ul className="mb-card-list">
          {brief.matters.map((m) => (
            <li key={m.key}>{m.title}</li>
          ))}
        </ul>
      )}
      <button type="button" className="agent-link" onClick={onOpen}>
        Open the brief
      </button>
    </div>
  );
}

export default function MarketBriefView({ brief, at }: { brief: MarketBrief; at?: string }) {
  const title = brief.mode === 'pre-open' ? 'Pre-open brief' : 'After-close note';
  const u = brief.underneath;
  const under: [string, string[]][] = [
    ['Leading sectors', u.leading],
    ['Lagging sectors', u.lagging],
    ['New 52-week highs', u.new_highs],
    ['New 52-week lows', u.new_lows],
    ['Delivery spikes', u.delivery],
    [`Largest deals${u.deals_as_of ? ` (${u.deals_as_of})` : ''}`, u.deals],
  ];
  return (
    <article className="mb">
      <header className="mb-head" data-tone={brief.tone}>
        <div className="mb-meta">
          <span>{title}</span>
          <span>
            {brief.day} · data to {brief.as_of ?? '—'}
            {at ? ` · written ${new Date(at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })}` : ''}
          </span>
          <span className="mb-tone">{TONE_WORD[brief.tone]}</span>
        </div>
        <p className="mb-headline">{brief.headline}</p>
      </header>

      {brief.review.length > 0 && (
        <Section title="This morning vs the close">
          <ul className="mb-list">
            {brief.review.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="What matters today">
        {brief.matters.length === 0 ? (
          <p className="mb-quiet">Nothing is far from normal today.</p>
        ) : (
          <ol className="mb-matters">
            {brief.matters.map((m) => (
              <li key={m.key}>
                <b>{m.title}</b>
                <p className="mb-fact">{m.fact}</p>
                <p className="mb-meaning">{m.meaning}</p>
              </li>
            ))}
          </ol>
        )}
      </Section>

      <Section title="Levels and what would change the read">
        {brief.range.low !== undefined && (
          <div className="mb-range" role="img" aria-label={`One-day range ${brief.range.low} to ${brief.range.high}`}>
            <span>{brief.range.low.toLocaleString('en-IN')}</span>
            <div className="mb-range-bar">
              <i />
            </div>
            <span>{brief.range.high?.toLocaleString('en-IN')}</span>
            <small>One-day range if VIX is right (about two days in three), around {brief.range.close?.toLocaleString('en-IN')}</small>
          </div>
        )}
        <ul className="mb-list">
          {brief.levels.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
        {brief.scenarios.length > 0 && (
          <ul className="mb-list mb-if">
            {brief.scenarios.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Coming up">
        <ul className="mb-list">
          {brief.coming_up.items.map((c) => (
            <li key={`${c.when}-${c.what}`}>
              <span className="mb-when">{c.when}</span> <b>{c.what}</b>
              <span className="mb-why"> {c.why}</span>
            </li>
          ))}
          {brief.coming_up.not_covered.map((n) => (
            <li key={n} className="mb-quiet">
              Not covered: {n}
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Your books">
        {brief.attention.length > 0 && (
          <ul className="mb-list mb-attn">
            {brief.attention.map((a, i) => (
              <li key={`${a.book}-${i}`}>
                <b>{a.book}</b> {a.why}
              </li>
            ))}
          </ul>
        )}
        <ul className="mb-list">
          {brief.books.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      </Section>

      <Section title="Scorecard" open={false}>
        <div className="mb-score">
          {brief.rows.map((r) => (
            <div key={r.signal} className="mb-row" data-word={r.word}>
              <span className="mb-mark" aria-hidden="true">
                {WORD_MARK[r.word] ?? '?'}
              </span>
              <b>{r.signal}</b>
              <span className="mb-word">{r.word}</span>
              <span className="mb-val">{r.value}</span>
              {r.normal && <span className="mb-norm">normal: {r.normal}</span>}
            </div>
          ))}
        </div>
      </Section>

      <Section title="Underneath" open={false}>
        <dl className="mb-under">
          {under
            .filter(([, v]) => v.length > 0)
            .map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{v.join(' · ')}</dd>
              </div>
            ))}
          {u.flows && (
            <div>
              <dt>FII / DII cash</dt>
              <dd>{u.flows}</dd>
            </div>
          )}
        </dl>
      </Section>

      {brief.note && (
        <Section title="Analyst note (model, not data)">
          <p className="mb-note">{brief.note}</p>
        </Section>
      )}

      <Section title="Detail" open={false}>
        {brief.detail.map(([heading, lines]) => (
          <div key={heading} className="mb-detail">
            <h4>{heading}</h4>
            <ul className="mb-list">
              {lines.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </div>
        ))}
        {brief.left_out.length > 0 && <p className="mb-quiet">Left out: {brief.left_out.join('; ')}</p>}
      </Section>
    </article>
  );
}
