'use client';

/**
 * The strategy builder.
 *
 * A strategy is five decisions, in the order it acts on them — what it may
 * trade, when it buys, when it sells, how much it holds, and what stops it —
 * after QuantConnect's universe / signal / sizing / risk split, with rules
 * written as sentences in Streak's manner and Composer's "rank and keep the
 * top N" (docs/RESEARCH/062). What is built here is a declared spec, checked by
 * the server on every edit and shown back in plain English, so what will run
 * is always readable before it runs.
 *
 * Nothing here computes a result. Saving writes the spec; backtesting runs it
 * through `/api/run/batch`, the same engine, result store and report as every
 * other strategy.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { api } from '@/lib/api';
import type {
  BuilderCatalog,
  BuilderCheck,
  BuilderComparator,
  BuilderIndicator,
  BuilderOperand,
  BuilderRule,
  BuilderRuleGroup,
  BuilderSpec,
  SavedBuilderStrategy,
  UniverseList,
} from '@/lib/api';
import { ASSET_CLASSES } from '@/lib/assetClasses';
import './builder.css';

const WINDOWS = [
  { label: '1Y', days: 365 },
  { label: '3Y', days: 3 * 365 },
  { label: '5Y', days: 5 * 365 },
  { label: '10Y', days: 3000 },
];

const MARKETS = ASSET_CLASSES.filter((c) => ['equity', 'us', 'crypto', 'fx'].includes(c.value));

function indicator(name: string, params: Record<string, number> = {}): BuilderOperand {
  return { kind: 'indicator', name, params, multiplier: 1, value: 0 };
}

function number(value: number): BuilderOperand {
  return { kind: 'value', name: 'close', params: {}, multiplier: 1, value };
}

function blank(): BuilderSpec {
  return {
    id: '',
    name: 'My strategy',
    description: '',
    universe: {
      asset_class: 'equity',
      universe: 'nifty100',
      instruments: [],
      min_price: 0,
      max_price: 0,
      min_turnover: 0,
    },
    entry: {
      match: 'all',
      rules: [{ left: indicator('close'), op: 'crosses_above', right: indicator('sma', { period: 50 }) }],
    },
    exit: {
      match: 'any',
      rules: [{ left: indicator('close'), op: 'crosses_below', right: indicator('sma', { period: 50 }) }],
    },
    sizing: { method: 'equal', max_positions: 10, vol_target_pct: 20, ranking: null },
    risk: { stop_loss_pct: 10, take_profit_pct: 0, trailing_stop_pct: 0, max_hold_days: 0 },
  };
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

/* ---------------- small inputs ---------------- */

function NumberInput({
  value,
  onChange,
  min,
  max,
  step,
  width = 76,
  label,
}: {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  width?: number;
  label: string;
}) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  return (
    <input
      className="sb-num"
      style={{ width }}
      type="number"
      aria-label={label}
      value={text}
      min={min}
      max={max}
      step={step ?? 'any'}
      onChange={(event) => {
        setText(event.target.value);
        const parsed = Number(event.target.value);
        if (event.target.value !== '' && Number.isFinite(parsed)) onChange(parsed);
      }}
    />
  );
}

function OperandEditor({
  value,
  onChange,
  catalog,
  allowNumber,
  label,
}: {
  value: BuilderOperand;
  onChange: (next: BuilderOperand) => void;
  catalog: BuilderCatalog;
  allowNumber: boolean;
  label: string;
}) {
  const groups = useMemo(() => {
    const out = new Map<string, BuilderIndicator[]>();
    for (const item of catalog.indicators) out.set(item.group, [...(out.get(item.group) ?? []), item]);
    return [...out.entries()];
  }, [catalog]);
  const definition = catalog.indicators.find((d) => d.name === value.name);

  const choose = (choice: string) => {
    if (choice === '__number') {
      onChange(number(value.kind === 'value' ? value.value : 0));
      return;
    }
    const next = catalog.indicators.find((d) => d.name === choice);
    const params: Record<string, number> = {};
    for (const p of next?.params ?? []) params[p.name] = p.default;
    onChange({ ...indicator(choice, params), multiplier: value.kind === 'indicator' ? value.multiplier : 1 });
  };

  return (
    <span className="sb-operand">
      <select
        aria-label={label}
        value={value.kind === 'value' ? '__number' : value.name}
        onChange={(event) => choose(event.target.value)}
        title={definition?.description}
      >
        {allowNumber && <option value="__number">A number</option>}
        {groups.map(([group, items]) => (
          <optgroup key={group} label={group}>
            {items.map((item) => (
              <option key={item.name} value={item.name}>
                {item.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      {value.kind === 'value' && (
        <NumberInput label={`${label} value`} value={value.value} onChange={(v) => onChange({ ...value, value: v })} />
      )}
      {value.kind === 'indicator' &&
        definition?.params.map((param) => (
          <label key={param.name} className="sb-param" title={param.label}>
            <span>{param.label}</span>
            <NumberInput
              label={`${definition.label} ${param.label}`}
              value={value.params[param.name] ?? param.default}
              min={param.min}
              max={param.max}
              step={param.integer ? 1 : 0.1}
              width={60}
              onChange={(v) => onChange({ ...value, params: { ...value.params, [param.name]: v } })}
            />
          </label>
        ))}
      {value.kind === 'indicator' && allowNumber && (
        <label className="sb-param" title="Scale the indicator, e.g. 1.05 for 5% above it">
          <span>×</span>
          <NumberInput
            label={`${label} multiplier`}
            value={value.multiplier}
            min={0.01}
            max={10}
            step={0.01}
            width={60}
            onChange={(v) => onChange({ ...value, multiplier: v })}
          />
        </label>
      )}
    </span>
  );
}

function RuleGroupEditor({
  title,
  hint,
  group,
  onChange,
  catalog,
  optional,
}: {
  title: string;
  hint: string;
  group: BuilderRuleGroup;
  onChange: (next: BuilderRuleGroup) => void;
  catalog: BuilderCatalog;
  optional?: boolean;
}) {
  const update = (index: number, rule: BuilderRule) =>
    onChange({ ...group, rules: group.rules.map((r, i) => (i === index ? rule : r)) });
  return (
    <div className="sb-rules">
      <div className="sb-rules-head">
        <span className="tfine">{hint}</span>
        {group.rules.length > 1 && (
          <span className="sb-match" role="group" aria-label={`${title} matching`}>
            {(['all', 'any'] as const).map((m) => (
              <button
                key={m}
                type="button"
                className="tchip sm"
                aria-pressed={group.match === m}
                onClick={() => onChange({ ...group, match: m })}
              >
                {m === 'all' ? 'All must hold' : 'Any one holds'}
              </button>
            ))}
          </span>
        )}
      </div>
      {group.rules.length === 0 && (
        <div className="tfine sb-none">{optional ? 'No rule. Exits come from the risk settings below.' : 'No rule yet.'}</div>
      )}
      {group.rules.map((rule, index) => (
        <div className="sb-rule" key={index}>
          <span className="sb-joiner">{index === 0 ? 'When' : group.match === 'all' ? 'and' : 'or'}</span>
          <OperandEditor
            label={`${title} rule ${index + 1} left`}
            value={rule.left}
            onChange={(left) => update(index, { ...rule, left })}
            catalog={catalog}
            allowNumber={false}
          />
          <select
            className="sb-op"
            aria-label={`${title} rule ${index + 1} comparison`}
            value={rule.op}
            onChange={(event) => update(index, { ...rule, op: event.target.value as BuilderComparator })}
          >
            {catalog.comparators.map((c) => (
              <option key={c.name} value={c.name}>
                {c.label}
              </option>
            ))}
          </select>
          <OperandEditor
            label={`${title} rule ${index + 1} right`}
            value={rule.right}
            onChange={(right) => update(index, { ...rule, right })}
            catalog={catalog}
            allowNumber
          />
          <button
            type="button"
            className="sb-remove"
            aria-label={`Remove ${title} rule ${index + 1}`}
            onClick={() => onChange({ ...group, rules: group.rules.filter((_, i) => i !== index) })}
          >
            ×
          </button>
        </div>
      ))}
      {group.rules.length < catalog.limits.max_rules && (
        <button
          type="button"
          className="tbtn sm"
          onClick={() =>
            onChange({
              ...group,
              rules: [...group.rules, { left: indicator('rsi', { period: 14 }), op: 'below', right: number(30) }],
            })
          }
        >
          + Add rule
        </button>
      )}
    </div>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section className="tpanel sb-step">
      <h3>
        <span className="sb-n">{n}</span>
        {title}
      </h3>
      {children}
    </section>
  );
}

/* ---------------- the page ---------------- */

type RunState = {
  status: 'idle' | 'saving' | 'running' | 'done' | 'failed';
  message: string;
  sharpe?: number;
  totalReturn?: number;
  maxDrawdown?: number;
  fills?: number;
};

export function StrategyBuilder({ onRefresh }: { onRefresh: () => void }) {
  const [catalog, setCatalog] = useState<BuilderCatalog | null>(null);
  const [universes, setUniverses] = useState<UniverseList | null>(null);
  const [saved, setSaved] = useState<SavedBuilderStrategy[]>([]);
  const [spec, setSpec] = useState<BuilderSpec>(blank);
  const [check, setCheck] = useState<BuilderCheck | null>(null);
  const [instrumentText, setInstrumentText] = useState('');
  const [days, setDays] = useState(5 * 365);
  const [tier, setTier] = useState<'A' | 'B'>('B');
  const [run, setRun] = useState<RunState>({ status: 'idle', message: '' });
  const [loadError, setLoadError] = useState('');
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    api.builderCatalog().then(setCatalog).catch((e) => setLoadError(String(e)));
    api.universes().then(setUniverses).catch(() => setUniverses(null));
    return () => {
      alive.current = false;
    };
  }, []);

  const refreshSaved = useCallback(() => {
    api
      .builderStrategies()
      .then((r) => alive.current && setSaved(r.strategies))
      .catch(() => undefined);
  }, []);
  useEffect(refreshSaved, [refreshSaved]);

  // Checked by the server on every edit, so the summary and the errors are
  // the server's reading of the spec, not a second copy of its rules here.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      api
        .builderValidate(spec)
        .then((result) => alive.current && setCheck(result))
        .catch((e) => alive.current && setCheck({ ok: false, errors: [String(e)] }));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [spec]);

  const edit = (change: (draft: BuilderSpec) => void) =>
    setSpec((current) => {
      const draft = clone(current);
      change(draft);
      return draft;
    });

  const load = (next: BuilderSpec, keepId: boolean) => {
    const copy = clone(next);
    if (!keepId) copy.id = '';
    setSpec(copy);
    setInstrumentText(copy.universe.instruments.join(', '));
    setRun({ status: 'idle', message: '' });
  };

  const backtest = async () => {
    setRun({ status: 'saving', message: 'Saving…' });
    try {
      const stored = await api.builderSave(spec);
      if (!stored.ok) {
        setRun({ status: 'failed', message: stored.errors.join(' ') });
        return;
      }
      setSpec(stored.spec);
      refreshSaved();
      onRefresh();
      const u = stored.spec.universe;
      const started = await api.runBatch([stored.id], days, tier, u.universe, u.instruments, u.asset_class);
      if (!started.ok || !started.job) {
        setRun({ status: 'failed', message: started.error ?? 'The backtest did not start.' });
        return;
      }
      setRun({ status: 'running', message: 'Backtesting…' });
      for (;;) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        if (!alive.current) return;
        const job = await api.batchJob(started.job);
        if (job.status === 'running' || job.status === 'queued') {
          setRun({ status: 'running', message: job.message || 'Backtesting…' });
          continue;
        }
        const item = job.result?.results?.[0];
        if (job.status === 'failed' || !item || item.error) {
          setRun({ status: 'failed', message: item?.error || job.error || 'The backtest failed.' });
        } else {
          setRun({
            status: 'done',
            message: 'Done',
            sharpe: item.result?.sharpe,
            totalReturn: item.result?.total_return,
            maxDrawdown: item.result?.max_drawdown,
            fills: item.result?.fills,
          });
        }
        refreshSaved();
        onRefresh();
        return;
      }
    } catch (e) {
      setRun({ status: 'failed', message: e instanceof Error ? e.message : String(e) });
    }
  };

  const save = async () => {
    const stored = await api.builderSave(spec);
    if (stored.ok) {
      setSpec(stored.spec);
      refreshSaved();
      onRefresh();
      setRun({ status: 'idle', message: `Saved as ${stored.id}.` });
    } else {
      setRun({ status: 'failed', message: stored.errors.join(' ') });
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm(`Delete ${id}? Its past backtests stay in the results.`)) return;
    await api.builderDelete(id);
    if (spec.id === id) load(blank(), false);
    refreshSaved();
    onRefresh();
  };

  if (loadError) {
    return (
      <div className="tnote bad">
        <span className="mk">▲</span>
        <div>The builder could not load: {loadError}</div>
      </div>
    );
  }
  if (!catalog) return <div className="tempty">Loading the builder…</div>;

  const u = spec.universe;
  const running = run.status === 'saving' || run.status === 'running';
  const pct = (value?: number) => (value === undefined ? '—' : `${(value * 100).toFixed(1)}%`);

  return (
    <div className="sb-page">
      <div className="tpanel sb-top">
        <div className="sb-name">
          <input
            aria-label="Strategy name"
            value={spec.name}
            maxLength={80}
            onChange={(event) => edit((d) => void (d.name = event.target.value))}
          />
          <input
            aria-label="Description"
            className="sb-desc"
            placeholder="What is the idea, in one sentence?"
            value={spec.description}
            maxLength={600}
            onChange={(event) => edit((d) => void (d.description = event.target.value))}
          />
        </div>
        <div className="sb-starts">
          <span className="tfine">Start from</span>
          <button type="button" className="tchip sm" onClick={() => load(blank(), false)}>
            Blank
          </button>
          {catalog.templates.map((t) => (
            <button key={t.id} type="button" className="tchip sm" title={t.description} onClick={() => load(t, false)}>
              {t.name}
            </button>
          ))}
        </div>
        {saved.length > 0 && (
          <div className="sb-starts">
            <span className="tfine">Saved</span>
            {saved.map((s) => (
              <span key={s.spec.id} className="sb-saved">
                <button
                  type="button"
                  className="tchip sm"
                  aria-pressed={spec.id === s.spec.id}
                  title={s.summary.join(' ')}
                  onClick={() => load(s.spec, true)}
                >
                  {s.spec.name}
                  {s.result.sharpe !== null && <em> · Sharpe {s.result.sharpe.toFixed(2)}</em>}
                </button>
                <button type="button" className="sb-remove" aria-label={`Delete ${s.spec.name}`} onClick={() => remove(s.spec.id)}>
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="sb-body">
        <div className="sb-steps">
          <Step n={1} title="What it may trade">
            <div className="sip-form">
              <label>
                Market
                <select
                  value={u.asset_class}
                  onChange={(event) =>
                    edit((d) => {
                      d.universe.asset_class = event.target.value;
                      if (event.target.value !== 'equity') d.universe.universe = 'all';
                      else if (d.universe.universe === 'all') d.universe.universe = 'nifty100';
                    })
                  }
                >
                  {MARKETS.map((m) => (
                    <option key={m.value} value={m.value}>
                      {m.label}
                    </option>
                  ))}
                </select>
              </label>
              {u.asset_class === 'equity' && (
                <label>
                  Universe
                  <select value={u.universe} onChange={(event) => edit((d) => void (d.universe.universe = event.target.value))}>
                    {(universes?.universes ?? [{ name: 'nifty100', symbols: 100 }]).map((x) => (
                      <option key={x.name} value={x.name}>
                        {x.name} ({x.symbols})
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label className="wide">
                Only these instruments (optional)
                <input
                  placeholder="RELIANCE, TCS, INFY"
                  value={instrumentText}
                  onChange={(event) => {
                    setInstrumentText(event.target.value);
                    const list = event.target.value
                      .split(/[,\s]+/)
                      .map((x) => x.trim().toUpperCase())
                      .filter(Boolean);
                    edit((d) => void (d.universe.instruments = list));
                  }}
                />
              </label>
              <label>
                Min price
                <NumberInput label="Minimum price" value={u.min_price} min={0} width={120} onChange={(v) => edit((d) => void (d.universe.min_price = v))} />
              </label>
              <label>
                Max price (0 = none)
                <NumberInput label="Maximum price" value={u.max_price} min={0} width={120} onChange={(v) => edit((d) => void (d.universe.max_price = v))} />
              </label>
              <label>
                Min 20-day turnover
                <NumberInput label="Minimum turnover" value={u.min_turnover} min={0} width={140} onChange={(v) => edit((d) => void (d.universe.min_turnover = v))} />
              </label>
            </div>
            {u.asset_class === 'equity' && u.universe === 'all' && (
              <p className="tfine">
                The whole panel is several thousand names, including thinly traded ones the cost model understates. Expect a long run; nifty100 or nifty250 is
                faster and more honest.
              </p>
            )}
          </Step>

          <Step n={2} title="When it buys">
            <RuleGroupEditor
              title="Entry"
              hint="Checked on every instrument at each day's close."
              group={spec.entry}
              onChange={(entry) => edit((d) => void (d.entry = entry))}
              catalog={catalog}
            />
          </Step>

          <Step n={3} title="When it sells">
            <RuleGroupEditor
              title="Exit"
              hint="Optional. A position also closes on the stops in step 5."
              group={spec.exit}
              onChange={(exit) => edit((d) => void (d.exit = exit))}
              catalog={catalog}
              optional
            />
          </Step>

          <Step n={4} title="How much it holds">
            <div className="sip-form">
              <label>
                Most positions at once
                <NumberInput
                  label="Maximum positions"
                  value={spec.sizing.max_positions}
                  min={1}
                  max={catalog.limits.max_positions}
                  step={1}
                  width={120}
                  onChange={(v) => edit((d) => void (d.sizing.max_positions = Math.round(v)))}
                />
              </label>
              <label>
                Position size
                <select
                  value={spec.sizing.method}
                  onChange={(event) =>
                    edit((d) => void (d.sizing.method = event.target.value as BuilderSpec['sizing']['method']))
                  }
                >
                  <option value="equal">Equal slots</option>
                  <option value="volatility_scaled">Equal slots, scaled for volatility</option>
                </select>
              </label>
              {spec.sizing.method === 'volatility_scaled' && (
                <label>
                  Volatility target %/yr
                  <NumberInput
                    label="Volatility target"
                    value={spec.sizing.vol_target_pct}
                    min={1}
                    max={200}
                    width={120}
                    onChange={(v) => edit((d) => void (d.sizing.vol_target_pct = v))}
                  />
                </label>
              )}
            </div>
            <p className="tfine">
              Each slot is {(100 / Math.max(1, spec.sizing.max_positions)).toFixed(1)}% of equity. Unused slots stay in cash.
            </p>
            <div className="sb-rank">
              <label className="sb-check">
                <input
                  type="checkbox"
                  checked={spec.sizing.ranking !== null}
                  onChange={(event) =>
                    edit(
                      (d) =>
                        void (d.sizing.ranking = event.target.checked
                          ? { by: indicator('roc', { period: 126 }), order: 'highest' }
                          : null)
                    )
                  }
                />
                When more instruments signal than there are slots, rank them
              </label>
              {spec.sizing.ranking ? (
                <span className="sb-rule">
                  <span className="sb-joiner">keep the</span>
                  <select
                    className="sb-op"
                    aria-label="Ranking order"
                    value={spec.sizing.ranking.order}
                    onChange={(event) =>
                      edit((d) => {
                        if (d.sizing.ranking) d.sizing.ranking.order = event.target.value as 'highest' | 'lowest';
                      })
                    }
                  >
                    <option value="highest">highest</option>
                    <option value="lowest">lowest</option>
                  </select>
                  <OperandEditor
                    label="Rank by"
                    value={spec.sizing.ranking.by}
                    onChange={(by) =>
                      edit((d) => {
                        if (d.sizing.ranking) d.sizing.ranking.by = by;
                      })
                    }
                    catalog={catalog}
                    allowNumber={false}
                  />
                </span>
              ) : (
                <span className="tfine">Otherwise the earliest entries keep their slots.</span>
              )}
            </div>
          </Step>

          <Step n={5} title="What stops it">
            <div className="sip-form">
              <label>
                Stop loss %
                <NumberInput label="Stop loss" value={spec.risk.stop_loss_pct} min={0} max={90} width={120} onChange={(v) => edit((d) => void (d.risk.stop_loss_pct = v))} />
              </label>
              <label>
                Take profit %
                <NumberInput label="Take profit" value={spec.risk.take_profit_pct} min={0} max={1000} width={120} onChange={(v) => edit((d) => void (d.risk.take_profit_pct = v))} />
              </label>
              <label>
                Trailing stop %
                <NumberInput label="Trailing stop" value={spec.risk.trailing_stop_pct} min={0} max={90} width={120} onChange={(v) => edit((d) => void (d.risk.trailing_stop_pct = v))} />
              </label>
              <label>
                Max days held
                <NumberInput
                  label="Maximum days held"
                  value={spec.risk.max_hold_days}
                  min={0}
                  max={2000}
                  step={1}
                  width={120}
                  onChange={(v) => edit((d) => void (d.risk.max_hold_days = Math.round(v)))}
                />
              </label>
            </div>
            <p className="tfine">0 turns a setting off. Stops are judged on closes, measured from the close the entry signalled on.</p>
          </Step>
        </div>

        <aside className="sb-side">
          <div className="tpanel">
            <h3>What it does</h3>
            {check === null && <p className="tfine">Checking…</p>}
            {check && check.ok && (
              <ol className="sb-summary">
                {check.summary.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ol>
            )}
            {check && !check.ok && (
              <div className="tnote bad">
                <span className="mk">▲</span>
                <div>
                  {check.errors.map((e) => (
                    <div key={e}>{e}</div>
                  ))}
                </div>
              </div>
            )}

            <h3 className="sb-h3">Backtest</h3>
            <div className="ttools">
              {WINDOWS.map((w) => (
                <button key={w.label} type="button" className="tchip sm" aria-pressed={days === w.days} onClick={() => setDays(w.days)}>
                  {w.label}
                </button>
              ))}
              <span className="ttools-actions">
                {(['B', 'A'] as const).map((t) => (
                  <button
                    key={t}
                    type="button"
                    className="tchip sm"
                    aria-pressed={tier === t}
                    title={t === 'B' ? 'Event-driven, order by order' : 'Vectorised, faster'}
                    onClick={() => setTier(t)}
                  >
                    Tier {t}
                  </button>
                ))}
              </span>
            </div>
            {check && check.ok && check.warmup >= days * 0.6 && (
              <p className="tfine">
                It needs {check.warmup} trading days before its first decision, which uses most of this window. Choose a longer one.
              </p>
            )}
            <div className="sb-actions">
              <button type="button" className="tbtn" disabled={!check?.ok || running} onClick={save}>
                Save
              </button>
              <button type="button" className="tbtn go" disabled={!check?.ok || running} onClick={backtest}>
                {running ? run.message : 'Save and backtest'}
              </button>
            </div>
            {run.status === 'failed' && (
              <div className="tnote bad">
                <span className="mk">▲</span>
                <div>{run.message}</div>
              </div>
            )}
            {run.status === 'idle' && run.message && <p className="tfine">{run.message}</p>}
            {run.status === 'done' && (
              <div className="sb-result">
                <div className="rpt-grid">
                  <div className="tstat-card">
                    <span>Sharpe</span>
                    <b>{run.sharpe === undefined ? '—' : run.sharpe.toFixed(2)}</b>
                  </div>
                  <div className="tstat-card">
                    <span>Return</span>
                    <b className={(run.totalReturn ?? 0) >= 0 ? 'pos' : 'neg'}>{pct(run.totalReturn)}</b>
                  </div>
                  <div className="tstat-card">
                    <span>Max drawdown</span>
                    <b className="neg">{pct(run.maxDrawdown)}</b>
                  </div>
                  <div className="tstat-card">
                    <span>Fills</span>
                    <b>{run.fills ?? '—'}</b>
                  </div>
                </div>
                <a className="tbtn go sb-report" href={`#report/${encodeURIComponent(spec.id)}`}>
                  Open the full report
                </a>
                <p className="tfine">
                  A screening run: it is recorded with this strategy but spends no trial, so the noise bar does not know about it. Every edit you test is
                  another attempt.
                </p>
              </div>
            )}
            <ul className="sb-caveats">
              {catalog.caveats.map((c) => (
                <li key={c} className="tfine">
                  {c}
                </li>
              ))}
            </ul>
          </div>
        </aside>
      </div>
    </div>
  );
}
