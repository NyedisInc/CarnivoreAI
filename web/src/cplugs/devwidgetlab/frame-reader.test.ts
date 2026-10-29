/** @vitest-environment jsdom */
import { describe, expect, it, vi } from 'vitest';
import { provideScenario, readReport, stageBottom, waitForReport, type HarnessState, type HarnessWindow } from './frame-reader';

const win = (state?: Partial<HarnessState>): HarnessWindow => ({
  __widgetHarness: state ? { ready: false, error: '', misses: [], ...state } : undefined,
  document: document.implementation.createHTMLDocument('f'),
});

describe('provideScenario', () => {
  it('hands the text over once, only when the frame waits for one', () => {
    const handed = vi.fn();
    expect(provideScenario(win({ provideScenario: handed }), '{"GET /x": 1}')).toBe(true);
    expect(handed).toHaveBeenCalledWith('{"GET /x": 1}');
    expect(provideScenario(win({ provideScenario: handed }), null)).toBe(false);
    expect(provideScenario(win(), '{}')).toBe(false);
    expect(handed).toHaveBeenCalledTimes(1);
  });
});

describe('readReport', () => {
  it('is null until the frame says ready, then carries its error, its misses and its result', () => {
    expect(readReport(win())).toBeNull();
    expect(readReport(win({ ready: false }))).toBeNull();
    expect(readReport(win({ ready: true, error: 'x', misses: ['GET /a'] }))).toEqual({ ready: true, error: 'x', misses: ['GET /a'] });
  });
});

describe('waitForReport', () => {
  it('resolves with the report once the frame is ready', async () => {
    const frame = win({ ready: false });
    setTimeout(() => { frame.__widgetHarness!.ready = true; }, 150);
    expect((await waitForReport(frame, () => false, 3000))?.ready).toBe(true);
  });

  it('gives null, never a drawn report, when the frame never says ready or the page stops caring', async () => {
    expect(await waitForReport(win({ ready: false }), () => false, 250)).toBeNull();
    expect(await waitForReport(win({ ready: false }), () => true, 3000)).toBeNull();
  });
});

describe('stageBottom', () => {
  it('is null when nothing is drawn', () => {
    expect(stageBottom(win())).toBeNull();
  });
});
