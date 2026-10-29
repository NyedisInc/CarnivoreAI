import { describe, expect, it } from 'vitest';
import type { LabSize } from '../sdk/widget-lab';
import { DESKTOP_WINDOW_MIN_PX, FRAME_MIN_HEIGHT_PX, FRAME_MIN_WIDTH_PX, FRAME_PATH, frameHeight, frameUrl, frameWidth, frameWindowWidth, type FrameSpec } from './frame-url';

const size = (over: Partial<LabSize>): LabSize => ({ name: 'm', w: 384, h: 256, viewport: 1600, declared: false, floor: false, ...over });
const spec: FrameSpec = { widget: 'core.notes', host: 'home', size: 'm', theme: 'carnivore', fixture: 'data', scenario: false };

describe('frameUrl', () => {
  it('names the harness page and its query, always as a lab frame', () => {
    const url = new URL(frameUrl(spec), 'http://x.test');
    expect(url.pathname).toBe(FRAME_PATH);
    expect(Object.fromEntries(url.searchParams)).toEqual({ widget: 'core.notes', zone: 'home', size: 'm', theme: 'carnivore', fixture: 'data', lab: '1' });
  });

  it('asks for the scenario wait only when told to, and never for a menu', () => {
    const url = new URL(frameUrl({ ...spec, scenario: true }), 'http://x.test');
    expect(url.searchParams.get('state')).toBeNull();
    expect(url.searchParams.get('scenario')).toBe('wait');
  });

  it('asks for the idle check only when told to', () => {
    expect(new URL(frameUrl(spec), 'http://x.test').searchParams.get('idle')).toBeNull();
    expect(new URL(frameUrl({ ...spec, idle: true }), 'http://x.test').searchParams.get('idle')).toBe('1');
  });

  it('keeps an analytics key whole in the query', () => {
    expect(new URL(frameUrl({ ...spec, widget: 'core.analytics:vitals' }), 'http://x.test').searchParams.get('widget')).toBe('core.analytics:vitals');
  });

  it('is always same-origin: a path, never a host', () => {
    expect(frameUrl(spec).startsWith('/static/')).toBe(true);
  });
});

describe('frame window', () => {
  it('is the box plus the stage padding, never below the menu-safe minimum', () => {
    expect(frameWidth(size({ w: 384 }))).toBe(Math.max(384 + 32, FRAME_MIN_WIDTH_PX));
    expect(frameWidth(size({ w: 1440 }))).toBe(1472);
    expect(frameWidth(size({ w: 240 }))).toBe(FRAME_MIN_WIDTH_PX);
  });

  it('draws the phone size in a phone-wide window, whatever the page is', () => {
    expect(frameWidth(size({ name: 'phone', w: 358, h: null, viewport: 390 }))).toBe(390);
  });

  it('draws every non-phone size in a desktop window, so the app\'s breakpoints see a desktop', () => {
    expect(frameWindowWidth(size({ w: 240 }))).toBe(1600);
    expect(frameWindowWidth(size({ w: 384 }))).toBe(1600);
    expect(frameWindowWidth(size({ w: 1700 }))).toBe(1732);
    expect(frameWindowWidth(size({ w: 320, viewport: 1100 }))).toBe(1100);
    for (const w of [240, 384, 600]) expect(frameWindowWidth(size({ w }))).toBeGreaterThanOrEqual(DESKTOP_WINDOW_MIN_PX);
  });

  it('keeps the phone size in its phone-wide window', () => {
    expect(frameWindowWidth(size({ name: 'phone', w: 358, h: null, viewport: 390 }))).toBe(390);
  });

  it('takes its height from the size, or the minimum when the content decides', () => {
    expect(frameHeight(size({ h: 960 }))).toBe(992);
    expect(frameHeight(size({ h: null }))).toBe(FRAME_MIN_HEIGHT_PX);
    expect(frameHeight(size({ h: 100 }))).toBe(FRAME_MIN_HEIGHT_PX);
  });
});
