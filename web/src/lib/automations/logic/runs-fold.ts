import { outputChanged, previousIndex } from './diff';
import type { ReportLookup } from './types';
import { slotOf, type FeedRow } from './feed';

export interface RunGroup {
  head: FeedRow;
  runs: FeedRow[];
}

export function foldRuns(runs: FeedRow[], lookup: ReportLookup): RunGroup[] {
  const out: RunGroup[] = [];
  let cur: RunGroup | null = null;
  const unchanged = (run: FeedRow): boolean => {
    const idx = runs.indexOf(run);
    const p = previousIndex(runs, idx, lookup);
    return p >= 0 && outputChanged(slotOf(runs[p]!, lookup), slotOf(run, lookup)) === false;
  };
  for (const r of runs) {
    const join = cur && r.status === cur.head.status && (r.reason ?? '') === (cur.head.reason ?? '') && (r.status !== 'succeeded' || unchanged(cur.runs[cur.runs.length - 1]!));
    if (join && cur) cur.runs.push(r);
    else {
      cur = { head: r, runs: [r] };
      out.push(cur);
    }
  }
  return out;
}
