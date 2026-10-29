/*  hidden  display: none */
import { harnessState } from './state';
import { isShellRoute } from '../opscenter/widgets/fixtures/app-world';
import { IDLE_SPAN_MS, idleVerdict, installVirtualTimers, trackTimers, type IdleTotals, type TimerTracker } from './idle-traffic';

export interface IdleCheck {
  shown: IdleTotals;
  hidden: IdleTotals;
  /*  hidden  */
  shell: number;
  shownRoutes: Record<string, number>;
  /*  hidden  */
  hiddenRoutes: Record<string, number>;
  failures: string[];
}

let tracker: TimerTracker | null = null;

function routeDelta(before: Record<string, number>, after: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [route, n] of Object.entries(after)) if (n > (before[route] ?? 0)) out[route] = n - (before[route] ?? 0);
  return out;
}

function total(routes: Record<string, number>): number {
  return Object.values(routes).reduce((sum, n) => sum + n, 0);
}

function widgetOnly(routes: Record<string, number>): Record<string, number> {
  return Object.fromEntries(Object.entries(routes).filter(([route]) => !isShellRoute(route)));
}

export function startIdleTracking(wanted: boolean): void {
  if (wanted && !tracker) tracker = trackTimers(globalThis as unknown as Parameters<typeof trackTimers>[0]);
}

/*  hidden  */
export async function runIdleCheck(): Promise<IdleCheck> {
  if (!tracker) throw new Error('the idle check needs the page opened with idle=1');
  const target = globalThis as unknown as Parameters<typeof installVirtualTimers>[0];
  const clock = installVirtualTimers(target, tracker.stop());
  tracker = null;
  const body = document.body;
  const was = body.style.display;
  const minute = async (): Promise<Record<string, number>> => {
    const before = { ...harnessState.counts };
    await clock.advance(IDLE_SPAN_MS);
    return routeDelta(before, harnessState.counts);
  };
  try {
    await clock.advance(IDLE_SPAN_MS);
    const shownRoutes = widgetOnly(await minute());
    body.style.display = 'none';
    const allHidden = await minute();
    const hiddenRoutes = widgetOnly(allHidden);
    const shown = { requests: total(shownRoutes), bytes: 0 };
    const hidden = { requests: total(hiddenRoutes), bytes: 0 };
    return { shown, hidden, shell: total(allHidden) - hidden.requests, shownRoutes, hiddenRoutes, failures: idleVerdict({ shown, hidden }) };
  } finally {
    body.style.display = was;
    clock.restore();
  }
}
