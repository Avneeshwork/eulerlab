import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'EulerLab',
  description: 'Author a strategy, backtest it against real Indian equity history.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
