import { describe, expect, test } from 'vitest';
import { bannerKind, computeShowBanner, type VersionWatchState } from './version-watch.svelte';

function state(overrides: Partial<VersionWatchState> = {}): VersionWatchState {
  return {
    pageVersion: 'v1.12.2',
    latestServerVersion: '',
    dismissedVersion: '',
    pageClientBuild: 'aaa',
    latestClientBuild: '',
    dismissedClientBuild: '',
    ...overrides,
  };
}

describe('computeShowBanner', () => {
  test('hidden when no hello has reported a server version yet', () => {
    expect(computeShowBanner(state())).toBe(false);
  });

  test('hidden when the latest server version matches the page', () => {
    expect(computeShowBanner(state({ latestServerVersion: 'v1.12.2' }))).toBe(false);
  });

  test('shown when the server answers with a different version', () => {
    expect(computeShowBanner(state({ latestServerVersion: 'v1.12.3' }))).toBe(true);
  });

  test('hidden again once that exact version has been dismissed', () => {
    expect(
      computeShowBanner(
        state({ latestServerVersion: 'v1.12.3', dismissedVersion: 'v1.12.3' }),
      ),
    ).toBe(false);
  });

  test('a THIRD version after a dismiss reopens the banner', () => {
    expect(
      computeShowBanner(
        state({ latestServerVersion: 'v1.12.4', dismissedVersion: 'v1.12.3' }),
      ),
    ).toBe(true);
  });

  test('an unresolved page version never counts as a mismatch', () => {
    expect(
      computeShowBanner(state({ pageVersion: '', latestServerVersion: 'v1.12.3' })),
    ).toBe(false);
  });

  test('an unresolved server answer never counts as a mismatch', () => {
    expect(computeShowBanner(state({ latestServerVersion: '' }))).toBe(false);
  });

  test('the page chip spelling and the bare hello tag are the same build (#797)', () => {
    expect(
      computeShowBanner(state({ pageVersion: 'v1.12.6', latestServerVersion: '1.12.6' })),
    ).toBe(false);
  });

  test('a genuinely different bare hello still shows against a chip spelling (#797)', () => {
    expect(
      computeShowBanner(state({ pageVersion: 'v1.12.6', latestServerVersion: '1.12.7' })),
    ).toBe(true);
  });

  test('dismissing the bare spelling covers the same build (#797)', () => {
    expect(
      computeShowBanner(
        state({ pageVersion: 'v1.12.6', latestServerVersion: '1.12.7', dismissedVersion: 'v1.12.7' }),
      ),
    ).toBe(false);
  });

  test('same version but a different client build shows the client pill (hot-sync)', () => {
    const s = state({ latestServerVersion: 'v1.12.2', latestClientBuild: 'bbb' });
    expect(computeShowBanner(s)).toBe(true);
    expect(bannerKind(s)).toBe('client');
  });

  test('the same client build stays quiet', () => {
    expect(bannerKind(state({ latestClientBuild: 'aaa' }))).toBe(null);
  });

  test('an unresolved client build on either side never shows', () => {
    expect(bannerKind(state({ latestClientBuild: 'bbb', pageClientBuild: '' }))).toBe(null);
    expect(bannerKind(state({ latestClientBuild: '' }))).toBe(null);
  });

  test('a version change wins over a client build change', () => {
    expect(
      bannerKind(state({ latestServerVersion: 'v1.12.3', latestClientBuild: 'bbb' })),
    ).toBe('version');
  });

  test('dismissing a client build hides it, a further build reopens it', () => {
    expect(
      bannerKind(state({ latestClientBuild: 'bbb', dismissedClientBuild: 'bbb' })),
    ).toBe(null);
    expect(
      bannerKind(state({ latestClientBuild: 'ccc', dismissedClientBuild: 'bbb' })),
    ).toBe('client');
  });
});
