import { describe, expect, test } from 'vitest';
import { HYSTERESIS } from '../lib/states';
import { TIER_HEIGHTS, TIER_WIDTHS, pickTier, tierOf } from './density';

const panelW = TIER_WIDTHS.find((step) => step.name === 'panel')!.min;
const fullW = TIER_WIDTHS.find((step) => step.name === 'full')!.min;
const panelH = TIER_HEIGHTS.find((step) => step.name === 'panel')!.min;

describe('analytics density tiers', () => {
  test('the box picks tile, panel or full; the poorer of width and height wins', () => {
    expect(pickTier(100, 100).tier).toBe('tile');
    expect(pickTier(panelW, panelH).tier).toBe('panel');
    expect(pickTier(900, 900).tier).toBe('full');
    expect(pickTier(900, 100).tier).toBe('tile');
    expect(pickTier(100, 900).tier).toBe('tile');
    expect(tierOf('full', 'panel')).toBe('panel');
  });

  test('hysteresis: a step turns off only HYSTERESIS px below where it turned on', () => {
    const up = pickTier(fullW, 900);
    expect(up.tier).toBe('full');
    const held = pickTier(fullW - HYSTERESIS, 900, up);
    expect(held.tier).toBe('full');
    const dropped = pickTier(fullW - HYSTERESIS - 1, 900, up);
    expect(dropped.tier).toBe('panel');
  });

  test('without the previous step the same width flips at the minimum: hysteresis is what holds it', () => {
    expect(pickTier(fullW - 1, 900).tier).toBe('panel');
    expect(pickTier(fullW - 1, 900, { w: 'full', h: 'full' }).tier).toBe('full');
  });

  test('height holds independently of width', () => {
    const at = pickTier(900, 330);
    expect(at.tier).toBe('full');
    expect(pickTier(900, 330 - HYSTERESIS, at).tier).toBe('full');
    expect(pickTier(900, 330 - HYSTERESIS - 1, at).tier).toBe('panel');
  });
});
