import { redirect } from 'next/navigation';

/**
 * There is one interface, and it lives at `/terminal`.
 *
 * Two grew in parallel: this root page and the terminal. They read the same
 * API, showed overlapping subsets of it, and disagreed about which was
 * authoritative — the root page still had its own fleet table, its own
 * instrument picker and its own equity chart, none of which had learned about
 * US equity, the cost router, walk-forward, or anything else built since.
 *
 * A second interface is not a spare; it is a second thing to keep correct, and
 * the one nobody looks at is the one that quietly goes wrong.
 */
export default function Home() {
  redirect('/terminal');
}
