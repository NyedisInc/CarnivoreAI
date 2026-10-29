import { describe, expect, test } from 'vitest';
import { toastFor } from './session-died-toast';

describe('toastFor', () => {
  test('says the died sentence, lowercase, as a local card', () => {
    const toast = toastFor({ session_id: 'ses_1', session_name: 'api' }, 5);
    expect(toast?.body).toBe('api stopped unexpectedly');
    expect(toast?.kind).toBe('SessionDied');
    expect(toast?.local).toBe(true);
    expect(toast?.session_id).toBeNull();
    expect(toast?.id).toBe('sessiondied:ses_1:5');
  });

  test('a frame with no session raises nothing', () => {
    expect(toastFor({ session_name: 'api' })).toBeNull();
  });

  test('a frame with no name falls back to the session id, never blank', () => {
    expect(toastFor({ session_id: 'ses_9' })?.body).toBe('ses_9 stopped unexpectedly');
  });
});
