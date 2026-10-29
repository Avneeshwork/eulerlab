import type { Metadata } from 'next';
import '../tokens.css';
import './terminal.css';
import './shell.css';
import './theme.css';
import Assistant from '@/components/Assistant';

export const metadata: Metadata = {
  title: 'EulerLab',
  description: 'Strategies ranked by evidence, not by return.',
};

/**
 * The terminal lives at its own route while it is being built.
 *
 * The existing workbench at `/` keeps working untouched. Once the terminal
 * covers everything the workbench does, `/` becomes this and the old palette
 * is deleted in one commit — rather than the two bleeding into each other over
 * several, which is how an interface ends up with two of everything.
 */
export default function TerminalLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="terminal">
      {children}
      {/* Inside `.terminal`, not in the root layout: the colour and spacing
          tokens are defined on this element, so outside it the button has no
          size, position or colour and cannot be seen (2026-10-12). */}
      <Assistant />
    </div>
  );
}
