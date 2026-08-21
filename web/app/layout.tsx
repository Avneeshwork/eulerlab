import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'EulerLab — strategy workbench',
  description: 'Author a strategy, backtest it against real Indian equity history.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        {/* Two families, chosen from the Robinhood reference (docs/RESEARCH/018):
            one precise sans against one warm serif, which is the structural
            choice both generations of their identity make. Neither original is
            licensable — Newsreader stands in for Martina Plantijn, a Dutch
            old-style with real ink traps; Archivo for Phonic. JetBrains Mono is
            a functional need in a column of numbers, not a stylistic one.
            IBM Plex still serves the original workbench at / until the terminal
            replaces it. */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;450;500;600&family=IBM+Plex+Serif:wght@500;600&family=JetBrains+Mono:wght@400;500;700&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;1,6..72,400&display=swap"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
