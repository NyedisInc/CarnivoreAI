import { describe, expect, test, vi } from 'vitest';

const openLedger = vi.fn();
const openThemes = vi.fn();
const openPlugins = vi.fn();
const openSessionsScreen = vi.fn();

vi.mock('../api', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../api');
  return { ...actual, openLedger, openThemes, openPlugins };
});

vi.mock('../../lib/sessions-page/screen-host', () => ({ openSessionsScreen }));

describe('every card whose meta declares rightControl "view-all" has a bound action', () => {
  test('closed-sessions, projects and ledger each call their page opener', async () => {
    const { REGISTRY } = await import('./registry');

    expect(typeof REGISTRY['closed-sessions'].onRightControl).toBe('function');
    REGISTRY['closed-sessions'].onRightControl!();
    expect(openSessionsScreen).toHaveBeenCalledTimes(1);

    expect(typeof REGISTRY.projects.onRightControl).toBe('function');
    REGISTRY.projects.onRightControl!();
    expect(openSessionsScreen).toHaveBeenCalledTimes(2);

    expect(typeof REGISTRY.ledger.onRightControl).toBe('function');
    REGISTRY.ledger.onRightControl!();
    expect(openLedger).toHaveBeenCalledTimes(1);
  });

  test('running-sessions and themes were already wired and stay that way', async () => {
    const { REGISTRY } = await import('./registry');
    expect(typeof REGISTRY['running-sessions'].onRightControl).toBe('function');
    REGISTRY['running-sessions'].onRightControl!();
    expect(openSessionsScreen).toHaveBeenCalledTimes(1);
    expect(typeof REGISTRY.themes.onRightControl).toBe('function');
  });

  test('plugins opens the plugins page, now that it exists (issues #482, #765)', async () => {
    const { REGISTRY } = await import('./registry');
    const { META } = await import('../engine/meta');
    expect(META.plugins.rightControl).toBe('view-all');
    expect(typeof REGISTRY.plugins.onRightControl).toBe('function');
    REGISTRY.plugins.onRightControl!();
    expect(openPlugins).toHaveBeenCalledTimes(1);
  });
});
