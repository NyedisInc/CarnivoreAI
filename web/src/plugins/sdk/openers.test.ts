import { afterEach, expect, it } from 'vitest';
import { postedPageOpener, registerPostedPageOpener, resetPostedPageOpener } from './artifact-opener';
import { registerRoundOpener, resetRoundOpener, roundOpener } from './round-opener';

afterEach(() => {
  resetRoundOpener();
  resetPostedPageOpener();
});

it('withdraws the round opener while its plugin is off', () => {
  let on = true;
  const open = async (): Promise<void> => undefined;
  registerRoundOpener(open, () => on);
  expect(roundOpener()).toBe(open);
  on = false;
  expect(roundOpener()).toBeNull();
  on = true;
  expect(roundOpener()).toBe(open);
});

it('withdraws the posted-page opener while its plugin is off', () => {
  let on = false;
  const open = async (): Promise<boolean> => true;
  registerPostedPageOpener(open, () => on);
  expect(postedPageOpener()).toBeNull();
  on = true;
  expect(postedPageOpener()).toBe(open);
});

it('keeps an opener registered without a switch always on', () => {
  const open = async (): Promise<void> => undefined;
  registerRoundOpener(open);
  expect(roundOpener()).toBe(open);
});
