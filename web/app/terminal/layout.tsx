import type { Metadata } from 'next';
import '../tokens.css';
import './terminal.css';

export const metadata: Metadata = {
  title: 'EulerLab Terminal',
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
  return <div className="terminal">{children}</div>;
}
