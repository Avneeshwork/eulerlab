'use client';

/**
 * The terminal shell: top bar, hero, and whichever surface is selected.
 *
 * Built from the Robinhood reference (docs/RESEARCH/018) with two deliberate
 * inversions, both recorded in ADR-041:
 *
 *   1. Their hero number is your money. Ours is the noise bar, because that is
 *      the number that actually decides anything. A strategy's return in that
 *      slot would be the layout itself arguing that return is what matters.
 *   2. Their accent tracks profit. Ours tracks evidence — green means "cleared
 *      the bar", never "did well".
 *
 * Window and tier live here rather than in the Run tab because the library's
 * per-row Backtest button uses them too, and two surfaces silently running
 * different windows would produce two incomparable numbers under one name.
 */

import { useCallback, useEffect, useState } from 'react';
import { CommandPalette } from '@/components/CommandPalette';
import { BuildTab } from '@/components/terminal/BuildTab';
import { DataTab } from '@/components/terminal/DataTab';
import { DeployDialog } from '@/components/terminal/DeployDialog';
import { InstrumentsTab } from '@/components/terminal/InstrumentsTab';
import { Library } from '@/components/terminal/Library';
import { LiveTab } from '@/components/terminal/LiveTab';
import { RunTab } from '@/components/terminal/RunTab';
import { api } from '@/lib/api';
import type { Fleet, FleetStrategy } from '@/lib/api';

const NAV = ['Library', 'Build', 'Run', 'Instruments', 'Live', 'Data'] as const;
type Tab = (typeof NAV)[number];

export default function TerminalPage() {
  const [tab, setTab] = useState<Tab>('Library');
  const [fleet, setFleet] = useState<Fleet | null>(null);
  const [problem, setProblem] = useState('');
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [dark, setDark] = useState<boolean | null>(null);
  const [deploying, setDeploying] = useState<FleetStrategy | null>(null);
  const [days, setDays] = useState(800);
  const [tier, setTier] = useState<'A' | 'B'>('B');

  const workspace = '';

  const refresh = useCallback(() => {
    api
      .fleet()
      .then((next) => {
        setFleet(next);
        setProblem('');
      })
      .catch(() => setProblem('Cannot reach the API. Is it running on :8000?'));
  }, []);

  useEffect(refresh, [refresh]);

  // Null means "follow the OS", which is the state most people are in. Only an
  // explicit choice stamps the attribute.
  useEffect(() => {
    const root = document.querySelector('.terminal');
    if (!root) return;
    if (dark === null) root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', dark ? 'dark' : 'light');
  }, [dark]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const measured = fleet?.strategies.filter((s) => s.sharpe !== null).length ?? 0;
  const clearing = fleet?.strategies.filter((s) => s.clears_bar).length ?? 0;
  const trials = fleet?.strategies.reduce((sum, s) => sum + s.trials, 0) ?? 0;

  return (
    <>
      <header className="tbar">
        <span className="tbrand">
          <span className="tmark" aria-hidden="true">
            ↗
          </span>
          eulerlab
        </span>
        <nav className="tnav" aria-label="Sections">
          {NAV.map((item) => (
            <button
              key={item}
              type="button"
              aria-current={item === tab ? 'page' : undefined}
              onClick={() => setTab(item)}
            >
              {item}
            </button>
          ))}
        </nav>
        <div className="tright">
          <span
            className="tws"
            title="Evidence, strategies and credentials are scoped to this workspace (ADR-040)."
          >
            workspace <b>default</b>
          </span>
          <button className="tcmd" type="button" onClick={() => setPaletteOpen(true)}>
            Jump to anything <kbd>⌘K</kbd>
          </button>
          <button
            className="ticon"
            type="button"
            onClick={() => setDark((value) => (value === null ? true : value ? false : null))}
            title={
              dark === null ? 'Following your system theme' : dark ? 'Dark theme' : 'Light theme'
            }
            aria-label="Change theme"
          >
            {dark === null ? '◐' : dark ? '●' : '○'}
          </button>
        </div>
      </header>

      <div className="tpage">
        {tab === 'Library' && (
          <>
            <section className="thero">
              <div>
                <div className="theyebrow">The number to beat</div>
                <div className="thnum">
                  <b>{fleet ? fleet.bar.toFixed(2) : '—'}</b>
                  <span className="unit">
                    Sharpe{fleet && !fleet.bar_sigma_measured ? ', assumed' : ''}
                  </span>
                </div>
                <p className="thsub">
                  {trials} trials have been recorded, so this is the Sharpe the luckiest
                  worthless strategy would be expected to show by chance alone. A backtest
                  below it is not evidence of anything.
                </p>
              </div>
              <div className="thstats">
                <div className="thstat">
                  <span>Strategies</span>
                  <b>{fleet?.strategies.length ?? '—'}</b>
                </div>
                <div className="thstat">
                  <span>Measured</span>
                  <b>{fleet ? measured : '—'}</b>
                </div>
                <div className="thstat">
                  <span>Clearing it</span>
                  <b className={clearing > 0 ? 'on' : ''}>{fleet ? clearing : '—'}</b>
                </div>
              </div>
            </section>

            {fleet && !fleet.bar_sigma_measured && (
              <div className="tnote">
                <span className="mk" aria-hidden="true">
                  ▲
                </span>
                <div>
                  <p>
                    <b>The bar is assumed, not measured.</b> {fleet.bar_note}
                  </p>
                  <p style={{ marginTop: 6 }}>
                    Screening on this page spends no trial, so any search done here is
                    invisible to the bar — it stands lower than the work actually done
                    justifies.
                  </p>
                </div>
              </div>
            )}

            <Library
              fleet={fleet}
              problem={problem}
              window={days}
              tier={tier}
              onRefresh={refresh}
              onDeploy={setDeploying}
            />
          </>
        )}

        {tab === 'Build' && <BuildTab onRefresh={refresh} />}

        {tab === 'Run' && (
          <RunTab
            fleet={fleet}
            window={days}
            tier={tier}
            onWindow={setDays}
            onTier={setTier}
            onRefresh={refresh}
          />
        )}

        {tab === 'Instruments' && <InstrumentsTab />}

        {tab === 'Live' && (
          <LiveTab
            fleet={fleet?.strategies ?? []}
            workspace={workspace}
            onDeploy={setDeploying}
          />
        )}

        {tab === 'Data' && <DataTab workspace={workspace} />}
      </div>

      {paletteOpen && (
        <CommandPalette strategies={fleet?.strategies ?? []} onClose={() => setPaletteOpen(false)} />
      )}
      {deploying && (
        <DeployDialog
          strategy={deploying}
          workspace={workspace}
          onClose={() => setDeploying(null)}
        />
      )}
    </>
  );
}
