import type { FrameReport, IdleReport } from '../sdk/widget-lab';

export interface HarnessState {
  ready: boolean;
  error: string;
  misses: string[];
  result?: FrameReport['result'];
  provideScenario?: (text: string) => void;
  idle?: () => Promise<IdleReport>;
  show?: (request: { zone: string; size: string; theme: string; view?: unknown }) => Promise<unknown>;
}

export interface HarnessWindow {
  __widgetHarness?: HarnessState;
  document: Document;
}

export const WAIT_LIMIT_MS = 30_000;
export const POLL_MS = 100;

export function provideScenario(win: HarnessWindow, text: string | null): boolean {
  const state = win.__widgetHarness;
  if (text === null || !state?.provideScenario) return false;
  state.provideScenario(text);
  return true;
}

export function readReport(win: HarnessWindow): FrameReport | null {
  const state = win.__widgetHarness;
  if (!state?.ready) return null;
  return { ready: true, error: state.error, misses: [...state.misses], ...(state.result ? { result: state.result } : {}) };
}

export async function waitForReport(win: HarnessWindow, cancelled: () => boolean, limitMs: number = WAIT_LIMIT_MS): Promise<FrameReport | null> {
  const started = Date.now();
  while (!cancelled() && Date.now() - started < limitMs) {
    const report = readReport(win);
    if (report) return report;
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
  }
  return null;
}

export function stageBottom(win: HarnessWindow): number | null {
  const stage = win.document.querySelector('.wh-stage');
  return stage ? Math.ceil(stage.getBoundingClientRect().bottom) : null;
}
