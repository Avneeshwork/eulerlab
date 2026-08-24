'use client';

/**
 * One macro series as a small live chart.
 *
 * The scanner feeding the numbers view returns a single reading per symbol and
 * no history — enough to say where crude is, useless for saying what it has
 * been doing, which is most of why anyone looks at crude.
 *
 * ### Two mechanics the widget insists on
 *
 * It looks for its own container structure. The script has to sit inside a
 * `tradingview-widget-container` next to an empty
 * `tradingview-widget-container__widget` div, and appending it to a bare node
 * renders nothing at all — silently, with no console error. The first version
 * of this file did exactly that and drew empty boxes.
 *
 * And it is mounted eagerly. An IntersectionObserver saved seventeen script
 * loads and cost the charts entirely whenever the observer did not fire, which
 * is a poor trade: the widgets are small, and a chart that sometimes does not
 * appear is worse than one that always loads.
 */

import { useEffect, useRef } from 'react';

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

  useEffect(() => {
    const node = holder.current;
    if (!node) return;
    node.innerHTML = '';

    const dark =
      document.documentElement.dataset.theme === 'dark' ||
      (!document.documentElement.dataset.theme &&
        window.matchMedia('(prefers-color-scheme: dark)').matches);

    // The structure the widget looks for. Without the inner __widget div it
    // writes nowhere and leaves an empty box behind.
    const container = document.createElement('div');
    container.className = 'tradingview-widget-container';
    const inner = document.createElement('div');
    inner.className = 'tradingview-widget-container__widget';
    container.appendChild(inner);

    const script = document.createElement('script');
    script.src =
      'https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js';
    script.async = true;
    script.type = 'text/javascript';
    script.innerHTML = JSON.stringify({
      symbol,
      width: '100%',
      height: 180,
      locale: 'en',
      dateRange: range,
      colorTheme: dark ? 'dark' : 'light',
      isTransparent: true,
      autosize: false,
      chartOnly: false,
      noTimeScale: false,
    });
    container.appendChild(script);
    node.appendChild(container);

    return () => {
      node.innerHTML = '';
    };
  }, [symbol, range]);

  return (
    <div className="minichart">
      <div className="minihead">{label}</div>
      <div className="miniholder" ref={holder} />
    </div>
  );
}
