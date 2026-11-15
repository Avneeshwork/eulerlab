"use client";

/**
 * Real money: H-0194 on Angel One (ADR-162, `deploy/live_money.py`).
 *
 * Enter an amount, a leverage and a daily loss cap; Preview shows the names and
 * rupees a name; Deploy (type DEPLOY) arms the next session only. The server's
 * clock does the rest: watchlist, 09:20 entry, a mark every minute, 15:10 exit.
 * Kill trips the kill switch and closes today's positions. Clearing a tripped
 * switch is not on this screen: it needs the separate KILLSWITCH_TOKEN.
 */

import { useCallback, useEffect, useState } from "react";

import { Info } from "@/components/terminal/ui";

type Pick = {
  symbol: string;
  side: number;
  gap: number;
  quantity: number;
  notional: number;
  spread_bps: number;
};
type OrderRow = {
  symbol: string;
  event: string;
  detail?: string;
  view?: {
    status?: string;
    filled?: number;
    average_price?: number;
    reason?: string;
  } | null;
};
type PnlRow = {
  symbol: string;
  side: number;
  quantity: number;
  entry: number;
  mark: number;
  closed: boolean;
  net: number;
};
type Day = {
  plan?: {
    status: string;
    why?: string;
    data_through?: string;
    dropped?: Record<string, number>;
  };
  dry_run?: {
    status: string;
    why?: string;
    picks?: Pick[];
    at?: string;
    passed?: number;
  };
  open?: {
    status: string;
    why?: string;
    picks?: Pick[];
    orders?: OrderRow[];
    at?: string;
  };
  watch?: { rows: PnlRow[]; net: number; at: string; stopped?: string };
  close?: { status: string; orders?: OrderRow[] };
};
type Status = {
  strategy: string;
  deploy: {
    status?: string;
    for_session?: string;
    armed_at?: string;
    stopped_why?: string;
    settings?: { capital: number; leverage: number; loss_cap: number };
    sizing?: { names: number; per_name: number };
    notes?: string[];
  };
  kill_switch: { tripped: boolean; reason: string };
  clock: string;
  now_ist: string;
  days: Record<string, Day>;
};
type Position = Pick & { price: number; est_cost: number };
type WhatIf = {
  from: string;
  why?: string;
  passed?: number;
  too_dear?: number;
  positions: Position[];
  exposure_used?: number;
  est_cost?: number;
};
type Preview = {
  what_if: WhatIf;
  exposure: number;
  names: number;
  per_name: number;
  refused: string;
  notes: string[];
  for_session: string;
};

const inr = (v: number | undefined | null) =>
  v === undefined || v === null
    ? "—"
    : `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

async function call<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  const text = await response.text();
  if (!response.ok) {
    let detail = text;
    try {
      detail = (JSON.parse(text) as { detail?: string }).detail ?? text;
    } catch {
      /* not JSON */
    }
    throw new Error(detail || `${path} returned ${response.status}`);
  }
  return JSON.parse(text) as T;
}

function Picks({ picks }: { picks: Pick[] }) {
  if (!picks.length)
    return <div className="tempty">No stock passed: no trade that day.</div>;
  return (
    <table className="ttable">
      <thead>
        <tr>
          <th>Stock</th>
          <th>Side</th>
          <th className="r">Gap</th>
          <th className="r">Qty</th>
          <th className="r">Value</th>
          <th className="r">Spread</th>
        </tr>
      </thead>
      <tbody>
        {picks.map((p) => (
          <tr key={p.symbol}>
            <td>
              <b>{p.symbol}</b>
            </td>
            <td>{p.side > 0 ? "Buy (gap down)" : "Short (gap up)"}</td>
            <td className="r">{(p.gap * 100).toFixed(2)}%</td>
            <td className="r">{p.quantity}</td>
            <td className="r">{inr(p.notional)}</td>
            <td className="r">{p.spread_bps} bps</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Holdings({
  w,
  names,
  perName,
}: {
  w: WhatIf;
  names: number;
  perName: number;
}) {
  if (!w.from) return <div style={{ marginTop: 8 }}>{w.why}</div>;
  return (
    <div style={{ marginTop: 10 }}>
      <b>You would hold</b> (on the {w.from} quotes: {w.passed} stock(s) passed
      the rule
      {w.too_dear ? `, ${w.too_dear} too dear for one share at this size` : ""})
      {w.positions.length === 0 ? (
        <div>No position at this size.</div>
      ) : (
        <table className="ttable">
          <thead>
            <tr>
              <th>Stock</th>
              <th>Side</th>
              <th className="r">Gap</th>
              <th className="r">Price</th>
              <th className="r">Qty</th>
              <th className="r">Value</th>
              <th className="r">Est. costs</th>
            </tr>
          </thead>
          <tbody>
            {w.positions.map((p) => (
              <tr key={p.symbol}>
                <td>
                  <b>{p.symbol}</b>
                </td>
                <td>{p.side > 0 ? "Buy" : "Short"}</td>
                <td className="r">{(p.gap * 100).toFixed(2)}%</td>
                <td className="r">{p.price}</td>
                <td className="r">{p.quantity}</td>
                <td className="r">{inr(p.notional)}</td>
                <td className="r">₹{p.est_cost.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {w.positions.length < names && (
        <div>
          This amount allows up to {names} name(s) at {inr(perName)} each, but
          only {w.passed} stock(s) passed that day, so{" "}
          {names - w.positions.length} slot(s) stay empty and the money is not
          used. The backtest averaged about 5 stocks a day.
        </div>
      )}
      {w.positions.length > 0 && (
        <div>
          Total {inr(w.exposure_used)} held, about ₹
          {(w.est_cost ?? 0).toFixed(2)} in costs for the day. Tomorrow&apos;s
          stocks will differ: the rule picks them at 09:20.
        </div>
      )}
    </div>
  );
}

export function LiveMoney() {
  const [status, setStatus] = useState<Status | null>(null);
  const [problem, setProblem] = useState("");
  const [capital, setCapital] = useState("1000");
  const [leverage, setLeverage] = useState("5");
  const [lossCap, setLossCap] = useState("150");
  const [confirm, setConfirm] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [funds, setFunds] = useState<number | null | undefined>(undefined);
  const [busy, setBusy] = useState("");
  const [runs, setRuns] = useState(0);

  const read = useCallback(() => {
    call<Status>("/api/live-money")
      .then((s) => {
        setStatus(s);
        setProblem("");
      })
      .catch((e: Error) => setProblem(e.message));
  }, []);

  useEffect(() => {
    read();
    const id = window.setInterval(read, 15_000);
    return () => window.clearInterval(id);
  }, [read]);

  const sizeBody = () => ({
    capital: Number(capital),
    leverage: Number(leverage),
    loss_cap: Number(lossCap),
  });

  useEffect(() => {
    const body = sizeBody();
    if (!(body.capital > 0 && body.leverage >= 1 && body.loss_cap > 0)) {
      setPreview(null);
      return;
    }
    const t = window.setTimeout(() => {
      call<Preview>("/api/live-money/preview", body)
        .then(setPreview)
        .catch((e: Error) => setProblem(e.message));
    }, 250);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [capital, leverage, lossCap, runs]);

  const act = async (label: string, path: string, body: unknown) => {
    setBusy(label);
    setProblem("");
    try {
      await call(path, body);
      read();
      setRuns((n) => n + 1);
    } catch (e) {
      setProblem((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  const deploy = status?.deploy ?? {};
  const armed = deploy.status === "armed";
  const tripped = status?.kill_switch.tripped ?? false;
  const days = Object.entries(status?.days ?? {}).sort(([a], [b]) =>
    a < b ? 1 : -1,
  );

  return (
    <div className="tpanel">
      <h3>Real money · H-0194 gap fade on Angel One</h3>
      <p className="tfine">
        Fades a 3% gap with no NSE filing: 09:20 in, 15:10 out (MIS), one
        session per Deploy.
        <Info>
          Short the gap-ups, buy the gap-downs. ETFs, ASM/GSM and trade-for-trade
          stocks are skipped. The backtest overstates this about 2x (research
          180).
        </Info>
      </p>

      {tripped && (
        <div className="tempty" style={{ borderColor: "var(--down)" }}>
          <b>Kill switch tripped:</b> {status?.kill_switch.reason}. Nothing can
          be sent until it is cleared with the separate token (
          <code>make kill-status</code> shows how).
        </div>
      )}
      {problem && <div className="tempty">{problem}</div>}

      <div
        style={{
          display: "flex",
          gap: 16,
          flexWrap: "wrap",
          alignItems: "end",
          margin: "12px 0",
        }}
      >
        <label>
          Amount (₹)
          <br />
          <input
            className="tinput sm"
            inputMode="decimal"
            value={capital}
            onChange={(e) => setCapital(e.target.value)}
          />
        </label>
        <label>
          Leverage
          <br />
          <select
            className="tinput sm"
            value={leverage}
            onChange={(e) => setLeverage(e.target.value)}
          >
            {["1", "2", "3", "4", "5"].map((x) => (
              <option key={x} value={x}>
                {x}x
              </option>
            ))}
          </select>
        </label>
        <label>
          Daily loss cap (₹)
          <br />
          <input
            className="tinput sm"
            inputMode="decimal"
            value={lossCap}
            onChange={(e) => setLossCap(e.target.value)}
          />
        </label>
        <button
          className="tbtn sm"
          type="button"
          disabled={!!busy}
          onClick={() =>
            call<{ available: number | null }>("/api/live-money/funds", {})
              .then((f) => setFunds(f.available))
              .catch((e: Error) => setProblem(e.message))
          }
        >
          Check Angel cash
        </button>
        {funds !== undefined && (
          <span className="tfine">Available: {inr(funds)}</span>
        )}
      </div>

      {preview && (
        <div className="tfine" style={{ marginBottom: 12 }}>
          {preview.refused ? (
            <b>{preview.refused}</b>
          ) : (
            <>
              <b>
                {inr(preview.exposure)} of exposure: {preview.names} name(s) at{" "}
                {inr(preview.per_name)} each, for the session of{" "}
                {preview.for_session}.
              </b>
              {preview.notes.map((n) => (
                <div key={n}>{n}</div>
              ))}
              <Holdings
                w={preview.what_if}
                names={preview.names}
                perName={preview.per_name}
              />
              {funds !== undefined &&
                funds !== null &&
                funds < Number(capital) && (
                  <div style={{ color: "var(--down)" }}>
                    Angel shows {inr(funds)} available, less than the amount:
                    orders would be rejected.
                  </div>
                )}
            </>
          )}
        </div>
      )}

      <div
        style={{
          display: "flex",
          gap: 8,
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <button
          className="tbtn sm"
          type="button"
          disabled={!!busy || !preview || !!preview.refused}
          onClick={() => act("dry", "/api/live-money/dry-run", sizeBody())}
        >
          {busy === "dry"
            ? "Dry run… (about a minute)"
            : "Dry run now (sends nothing)"}
        </button>
        {!armed ? (
          <>
            <input
              className="tinput sm"
              placeholder="type DEPLOY"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              aria-label="Type DEPLOY to confirm real orders"
            />
            <button
              className="tbtn sm go"
              type="button"
              disabled={
                !!busy ||
                confirm !== "DEPLOY" ||
                !preview ||
                !!preview.refused ||
                tripped
              }
              onClick={() =>
                act("deploy", "/api/live-money/deploy", {
                  ...sizeBody(),
                  confirm,
                }).then(() => setConfirm(""))
              }
            >
              Deploy with real money
            </button>
          </>
        ) : (
          <button
            className="tbtn sm"
            type="button"
            disabled={!!busy}
            onClick={() => act("stop", "/api/live-money/stop", {})}
          >
            Stop (before 09:20)
          </button>
        )}
        <button
          className="tbtn sm danger"
          type="button"
          disabled={!!busy}
          onClick={() => {
            if (
              window.confirm(
                "Trip the kill switch and close every position of this book now?",
              )
            ) {
              void act("kill", "/api/live-money/kill", {});
            }
          }}
        >
          Kill: close all now
        </button>
      </div>

      <div className="tfine" style={{ marginTop: 12 }}>
        Deploy: <b>{deploy.status ?? "none"}</b>
        {deploy.for_session && <> for {deploy.for_session}</>}
        {deploy.settings && (
          <>
            {" "}
            · {inr(deploy.settings.capital)} at {deploy.settings.leverage}x,
            loss cap {inr(deploy.settings.loss_cap)}
          </>
        )}
        {deploy.stopped_why && <> · {deploy.stopped_why}</>} · clock:{" "}
        {status?.clock ?? "…"} · {status?.now_ist?.slice(11, 16)} IST
      </div>

      {days.map(([day, d]) => (
        <div key={day} style={{ marginTop: 16 }}>
          <h4>{day}</h4>
          {d.plan && (
            <div className="tfine">
              Watchlist: {d.plan.status}
              {d.plan.why && <> ({d.plan.why})</>}
              {d.plan.data_through && (
                <> · data through {d.plan.data_through}</>
              )}
            </div>
          )}
          {d.dry_run && (
            <>
              <div className="tfine">
                Dry run at {d.dry_run.at?.slice(11, 16)}: {d.dry_run.status}
                {d.dry_run.why && <> ({d.dry_run.why})</>} · nothing sent
              </div>
              {d.dry_run.picks && <Picks picks={d.dry_run.picks} />}
            </>
          )}
          {d.open && (
            <>
              <div className="tfine">
                Entry: {d.open.status}
                {d.open.why && <> ({d.open.why})</>}
              </div>
              {d.open.picks && <Picks picks={d.open.picks} />}
              {d.open.orders && d.open.orders.length > 0 && (
                <table className="ttable">
                  <thead>
                    <tr>
                      <th>Order</th>
                      <th>Sent</th>
                      <th>Broker status</th>
                      <th className="r">Filled</th>
                      <th className="r">Avg price</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...d.open.orders, ...(d.close?.orders ?? [])].map(
                      (o, i) => (
                        <tr key={`${o.symbol}-${i}`}>
                          <td>{o.symbol}</td>
                          <td>
                            {o.event}
                            {o.detail ? ` · ${o.detail}` : ""}
                          </td>
                          <td>
                            {o.view?.status ?? "—"}
                            {o.view?.reason ? ` · ${o.view.reason}` : ""}
                          </td>
                          <td className="r">{o.view?.filled ?? "—"}</td>
                          <td className="r">{o.view?.average_price ?? "—"}</td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              )}
            </>
          )}
          {d.watch && (
            <>
              <div className="tfine">
                P&amp;L after estimated costs at {d.watch.at.slice(11, 16)}:{" "}
                <b>{inr(d.watch.net)}</b>
                {d.watch.stopped && (
                  <>
                    {" "}
                    · <b>{d.watch.stopped}</b>
                  </>
                )}
              </div>
              <table className="ttable">
                <thead>
                  <tr>
                    <th>Stock</th>
                    <th className="r">Qty</th>
                    <th className="r">Entry</th>
                    <th className="r">Now</th>
                    <th className="r">Net</th>
                  </tr>
                </thead>
                <tbody>
                  {d.watch.rows.map((r) => (
                    <tr key={r.symbol}>
                      <td>
                        {r.symbol} {r.side > 0 ? "long" : "short"}
                        {r.closed ? " · closed" : ""}
                      </td>
                      <td className="r">{r.quantity}</td>
                      <td className="r">{r.entry}</td>
                      <td className="r">{r.mark}</td>
                      <td className="r">{inr(r.net)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          {d.close && <div className="tfine">Exit: {d.close.status}</div>}
        </div>
      ))}
    </div>
  );
}
