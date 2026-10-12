import type { Metadata } from 'next';
import './globals.css';
import Assistant from '@/components/Assistant';

export const metadata: Metadata = {
  title: 'EulerLab',
  description: 'Author a strategy, backtest it against real Indian equity history.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        {children}
        {/* Floats over every screen: questions about your own data (ADR-064). */}
        <Assistant />
      </body>
    </html>
  );
}
