/**
 * Everything the backtest report derives from what the API already returns.
 *
 * The report endpoint hands over the equity curve and the fill ledger. The
 * drawdown path, the worst episodes, the calendar returns and the round-trip
 * trades are all arithmetic on those two, so they are computed here rather
 * than adding fields to an endpoint the engine's self-tests already pin.
 *
 * Pure functions, no React, so each can be checked by hand against a small
 * input.
 */

import type { OrderRow } from '@/lib/api';

export type Point = { day: string; value: number };

/** Depth below the running peak at every point, as a negative fraction. */
export function drawdowns(values: number[]): number[] {
  let peak = values[0] ?? 0;
  return values.map((value) => {
    peak = Math.max(peak, value);
    return peak > 0 ? value / peak - 1 : 0;
  });
}

export type Episode = {
  start: string;
  trough: string;
  end: string | null;
  depth: number;
  /** Sessions from peak to recovery, or to the last session when still open. */
  length: number;
};

/** Every stretch below a previous high, deepest first. */
export function episodes(days: string[], values: number[], limit = 5): Episode[] {
  const dd = drawdowns(values);
  const out: Episode[] = [];
  let open: { startIndex: number; troughIndex: number } | null = null;
  for (let i = 0; i < dd.length; i += 1) {
    if (dd[i] < 0) {
      if (!open) open = { startIndex: Math.max(0, i - 1), troughIndex: i };
      else if (dd[i] < dd[open.troughIndex]) open.troughIndex = i;
    } else if (open) {
      out.push({
        start: days[open.startIndex],
        trough: days[open.troughIndex],
        end: days[i],
        depth: dd[open.troughIndex],
        length: i - open.startIndex,
      });
      open = null;
    }
  }
  if (open) {
    out.push({
      start: days[open.startIndex],
      trough: days[open.troughIndex],
      end: null,
      depth: dd[open.troughIndex],
      length: dd.length - 1 - open.startIndex,
    });
  }
  return out.sort((a, b) => a.depth - b.depth).slice(0, limit);
}

/**
 * Returns per calendar month and per year, compounded from the curve.
 *
 * Each period's return is its last value over the previous period's last
 * value, with the starting balance standing in before the first. A month the
 * curve does not reach is absent rather than zero — zero is a measurement.
 */
export function calendarReturns(
  days: string[],
  values: number[],
  starting: number
): { months: Map<string, number>; years: Map<string, number> } {
  const monthEnd = new Map<string, number>();
  const yearEnd = new Map<string, number>();
  days.forEach((day, i) => {
    monthEnd.set(day.slice(0, 7), values[i]);
    yearEnd.set(day.slice(0, 4), values[i]);
  });
  const chain = (ends: Map<string, number>) => {
    const out = new Map<string, number>();
    let previous = starting;
    for (const [key, value] of ends) {
      out.set(key, previous > 0 ? value / previous - 1 : 0);
      previous = value;
    }
    return out;
  };
  return { months: chain(monthEnd), years: chain(yearEnd) };
}

export type Trade = {
  symbol: string;
  side: 'Long' | 'Short';
  entryDay: string;
  entryPrice: number;
  exitDay: string | null;
  exitPrice: number | null;
  quantity: number;
  /** After the costs of both legs, the entry's share pro-rated by quantity. */
  net: number;
  /** Net over the capital the entry tied up. */
  returnPct: number;
  open: boolean;
};

type Lot = { day: string; price: number; qty: number; costPerUnit: number };

function sideOf(raw: string): 1 | -1 {
  return raw.toLowerCase().includes('sell') ? -1 : 1;
}

/**
 * Round trips from the fill ledger, matched first in, first out per symbol.
 *
 * A closing fill becomes one trade against the lots it consumes, so a bracket
 * exited in two legs is two trades, which is how a broker's tradebook and
 * TradingView's list of trades both count it. Whatever is still open at the
 * end is listed as open, priced at its entry.
 */
export function roundTrips(orders: OrderRow[]): Trade[] {
  const book = new Map<string, { dir: 1 | -1; lots: Lot[] }>();
  const trades: Trade[] = [];
  const sorted = orders
    .map((order, index) => ({ order, index }))
    .sort((a, b) => a.order.day.localeCompare(b.order.day) || a.index - b.index);

  for (const { order } of sorted) {
    const dir = sideOf(order.side);
    let qty = Math.abs(order.quantity);
    if (qty === 0) continue;
    const costPerUnit = order.cost / qty;
    const position = book.get(order.symbol);

    if (!position || position.lots.length === 0 || position.dir === dir) {
      const lots = position && position.lots.length > 0 ? position.lots : [];
      lots.push({ day: order.day, price: order.price, qty, costPerUnit });
      book.set(order.symbol, { dir, lots });
      continue;
    }

    // Closing against the open lots.
    let matched = 0;
    let entryValue = 0;
    let entryCost = 0;
    let firstDay = position.lots[0].day;
    while (qty > 0 && position.lots.length > 0) {
      const lot = position.lots[0];
      const take = Math.min(qty, lot.qty);
      if (matched === 0) firstDay = lot.day;
      matched += take;
      entryValue += take * lot.price;
      entryCost += take * lot.costPerUnit;
      lot.qty -= take;
      qty -= take;
      if (lot.qty <= 1e-12) position.lots.shift();
    }
    const entryPrice = entryValue / matched;
    const gross = (order.price - entryPrice) * matched * position.dir;
    const net = gross - entryCost - costPerUnit * matched;
    trades.push({
      symbol: order.symbol,
      side: position.dir === 1 ? 'Long' : 'Short',
      entryDay: firstDay,
      entryPrice,
      exitDay: order.day,
      exitPrice: order.price,
      quantity: matched,
      net,
      returnPct: entryValue > 0 ? net / entryValue : 0,
      open: false,
    });

    // A fill larger than the position flips it; the remainder opens the other way.
    if (qty > 0) {
      book.set(order.symbol, {
        dir,
        lots: [{ day: order.day, price: order.price, qty, costPerUnit }],
      });
    }
  }

  for (const [symbol, position] of book) {
    for (const lot of position.lots) {
      trades.push({
        symbol,
        side: position.dir === 1 ? 'Long' : 'Short',
        entryDay: lot.day,
        entryPrice: lot.price,
        exitDay: null,
        exitPrice: null,
        quantity: lot.qty,
        net: -lot.costPerUnit * lot.qty,
        returnPct: 0,
        open: true,
      });
    }
  }
  return trades;
}

export type TradeStats = {
  closed: number;
  open: number;
  wins: number;
  losses: number;
  winRate: number | null;
  grossProfit: number;
  grossLoss: number;
  profitFactor: number | null;
  averageWin: number | null;
  averageLoss: number | null;
  largestWin: number | null;
  largestLoss: number | null;
  expectancy: number | null;
};

export function tradeStats(trades: Trade[]): TradeStats {
  const closed = trades.filter((t) => !t.open);
  const wins = closed.filter((t) => t.net > 0);
  const losses = closed.filter((t) => t.net <= 0);
  const grossProfit = wins.reduce((s, t) => s + t.net, 0);
  const grossLoss = losses.reduce((s, t) => s + t.net, 0);
  return {
    closed: closed.length,
    open: trades.length - closed.length,
    wins: wins.length,
    losses: losses.length,
    winRate: closed.length ? wins.length / closed.length : null,
    grossProfit,
    grossLoss,
    profitFactor: grossLoss < 0 ? grossProfit / -grossLoss : null,
    averageWin: wins.length ? grossProfit / wins.length : null,
    averageLoss: losses.length ? grossLoss / losses.length : null,
    largestWin: wins.length ? Math.max(...wins.map((t) => t.net)) : null,
    largestLoss: losses.length ? Math.min(...losses.map((t) => t.net)) : null,
    expectancy: closed.length ? (grossProfit + grossLoss) / closed.length : null,
  };
}

/* ============================ SIP ============================ */

export type SipInstalment = { day: string; price: number; amount: number; units: number };

export type SipResult = {
  instalments: SipInstalment[];
  invested: number;
  units: number;
  value: number;
  /** Money-weighted annual return, solved from the dated cash flows. */
  xirr: number | null;
  /** Value path at every bar, beside cumulative money put in. */
  path: { day: string; invested: number; value: number }[];
  /** The same total invested once on the first instalment day, for comparison. */
  lumpSum: number;
};

/**
 * A monthly investment: on the first bar on or after `dayOfMonth` in each
 * month, buy `amount` of the instrument at that bar's close. Fractional units,
 * no costs and no taxes — it is a calculator over landed closes, not an
 * engine result. `stepUp` raises the instalment by that fraction every twelve
 * instalments.
 */
export function sip(
  bars: { time: string; close: number }[],
  amount: number,
  dayOfMonth = 1,
  stepUp = 0
): SipResult | null {
  const usable = bars.filter((b) => b.close > 0);
  if (usable.length < 2 || amount <= 0) return null;
  const instalments: SipInstalment[] = [];
  const bought = new Set<string>();
  let units = 0;
  let invested = 0;
  const path: SipResult['path'] = [];
  for (const bar of usable) {
    const month = bar.time.slice(0, 7);
    if (!bought.has(month) && Number(bar.time.slice(8, 10)) >= dayOfMonth) {
      bought.add(month);
      const step = Math.floor(instalments.length / 12);
      const due = amount * (1 + stepUp) ** step;
      const got = due / bar.close;
      units += got;
      invested += due;
      instalments.push({ day: bar.time, price: bar.close, amount: due, units: got });
    }
    path.push({ day: bar.time, invested, value: units * bar.close });
  }
  if (instalments.length === 0) return null;
  const last = usable[usable.length - 1];
  const value = units * last.close;
  const flows = [
    ...instalments.map((i) => ({ day: i.day, amount: -i.amount })),
    { day: last.time, amount: value },
  ];
  return {
    instalments,
    invested,
    units,
    value,
    xirr: xirr(flows),
    path,
    lumpSum: (invested / instalments[0].price) * last.close,
  };
}

/** Annual rate r with sum(amount / (1 + r)^(years since first)) = 0. */
export function xirr(flows: { day: string; amount: number }[]): number | null {
  if (flows.length < 2) return null;
  const t0 = Date.parse(flows[0].day);
  const years = flows.map((f) => (Date.parse(f.day) - t0) / (365 * 86_400_000));
  const npv = (r: number) => flows.reduce((s, f, i) => s + f.amount / (1 + r) ** years[i], 0);
  // Bisection on a bracket that holds any sane return: robust where Newton
  // diverges on a run with one instalment and a large swing.
  let low = -0.9999;
  let high = 10;
  let fLow = npv(low);
  if (fLow * npv(high) > 0) return null;
  for (let k = 0; k < 200; k += 1) {
    const mid = (low + high) / 2;
    const fMid = npv(mid);
    if (Math.abs(fMid) < 1e-7) return mid;
    if (fLow * fMid < 0) high = mid;
    else {
      low = mid;
      fLow = fMid;
    }
  }
  return (low + high) / 2;
}
