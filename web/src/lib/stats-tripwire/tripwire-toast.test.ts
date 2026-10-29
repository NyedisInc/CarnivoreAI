import { describe, expect, test } from 'vitest';

import { toastFor } from './tripwire-toast';

describe('toastFor', () => {
  test('a firing frame becomes a local, session-less card with value and threshold', () => {
    const toast = toastFor({ id: 'a', name: 'burn', state: 'firing', value: 9, threshold: 5, comparator: '>' }, 7);
    expect(toast).toMatchObject({ id: 'tripwire:a:7', session_id: null, local: true, kind: 'StatsTripwire' });
    expect(toast?.body).toBe('burn: 9 > 5');
    expect(toast?.title).toBe('tripwire fired');
  });

  test('a resolved frame says so', () => {
    expect(toastFor({ id: 'a', name: 'burn', state: 'ok', value: 1, threshold: 5, comparator: '>' })?.title).toBe(
      'tripwire resolved',
    );
  });

  test('a frame that is not a fire or resolve raises nothing', () => {
    expect(toastFor({ id: 'a', name: 'burn', state: 'unknown' })).toBeNull();
    expect(toastFor({ state: 'firing' })).toBeNull();
  });
});
