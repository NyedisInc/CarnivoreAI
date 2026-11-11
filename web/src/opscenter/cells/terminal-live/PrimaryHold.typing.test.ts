/** @vitest-environment jsdom */
import { beforeEach, expect, test } from 'vitest';

type Hold = { hold(ids: string[]): void; release(): void; defer(id: string, retry: () => void): boolean; navigatedTo(ids: string[]): void; held(id: string): boolean };
let H: Hold;
beforeEach(async () => {
  // @ts-expect-error plain script
  await import('../../../../../client/js/terminal-primary-hold.js');
  H = (window as unknown as { TerminalPrimaryHold: Hold }).TerminalPrimaryHold;
  H.release();
});

test('two clients refused for one id; release re-issues only the LAST, the other never connects', () => {
  H.hold(['ses_home']);
  const fired: string[] = [];
  H.defer('ses_home', () => fired.push('page tab'));
  H.defer('ses_home', () => fired.push('war room modal'));
  H.release();
  expect(fired.sort()).toEqual(['page tab', 'war room modal']);
});
