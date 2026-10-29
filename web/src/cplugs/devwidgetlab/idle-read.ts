/*  hidden  */
import type { IdleReport } from '../sdk/widget-lab';
import { waitForReport, type HarnessWindow } from './frame-reader';

export interface IdleReading {
  /*  hidden  */
  hidden: number;
  shown: number;
  /*  hidden  */
  routes: string[];
}

export function readingOf(report: IdleReport): IdleReading {
  const routes = Object.entries(report.hiddenRoutes).sort((a, b) => b[1] - a[1]).map(([route, n]) => `${route} x${n}`);
  return { hidden: report.hidden.requests, shown: report.shown.requests, routes };
}

export async function measureIdle(win: HarnessWindow, cancelled: () => boolean): Promise<IdleReading | null> {
  const report = await waitForReport(win, cancelled);
  const idle = win.__widgetHarness?.idle;
  if (!report || report.error || cancelled() || !idle) return null;
  return readingOf(await idle.call(win.__widgetHarness));
}
