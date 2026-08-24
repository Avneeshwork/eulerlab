'use client';

/**
 * One macro series as a small live chart.
 *
 * The scanner that feeds the macro band returns a single reading per symbol —
 * a level and a day's change, no history. That is enough to say where crude
 * is and useless for saying what it has been doing, which is most of why a
 * trader looks at crude at all.
 *
 * TradingView's mini-chart widget carries its own history, so each series gets
 * a real line rather than a number. It is a separate embed per symbol, which
 * is why these are lazy: seventeen widgets mounting at once on a tab nobody
 * has scrolled to is seventeen third-party scripts for nothing.
 */

import { useEffect, useRef, useState } from 'react';

export function MiniChart({
  symbol,
  label,
  range = '3M',
}: {
  symbol: string;
  label: string;
  range?: string;
}) {
  const holder = useRef<HTMLDivElement | null>(null);
  const [seen, setSeen] = useState(false);

  // Mounted only once it is about to be on screen. Without this the macro band
  // fires every widget the moment the tab renders.
  useEffect(() => {
    const node = holder.current;
    if (!node || seen) return;
    const watcher = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setSeen(true);
          watcher.disconnect();
        }
      },
      { rootMargin: '200px' },
    );
    watcher.observe(node);
    return () => watcher.disconnect();
  }, [seen]);

  useEffect(() => {
    const node = holder.current;
    if (!node || !seen) return;
    node.innerHTML = '';

    const dark =
      document.documentElement.dataset.theme === 'dark' ||
      (!document.documentElement.dataset.theme &&
        window.matchMedia('(prefers-color-scheme: dark)').matches);

    const script = document.createElement('script');
    script.src =
      'https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js';
    script.async = true;
    script.innerHTML = JSON.stringify({
      symbol,
      width: '100%',
      height: 140,
      locale: 'en',
      dateRange: range,
      colorTheme: dark ? 'dark' : 'light',
      isTransparent: true,
      autosize: false,
      largeChartUrl: '',
    });
    node.appendChild(script);

    return () => {
      node.innerHTML = '';
    };
  }, [symbol, range, seen]);

  return (
    <div className="minichart">
      <div className="minihead">{label}</div>
      <div className="miniholder" ref={holder} />
    </div>
  );
}
