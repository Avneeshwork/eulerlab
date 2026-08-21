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
        {/* IBM Plex: serif for headings, sans for text, mono for every number.
            A superfamily designed for technical communication, which is what
            this interface is — and deliberately not the system stack, which
            gave every panel the same undifferentiated weight. */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;450;500;600&family=IBM+Plex+Serif:wght@500;600&display=swap"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
