import { describe, expect, test } from 'vitest';
import { GLYPHS, glyphSvg } from '../../../../client/js/icons/glyphs.js';
import { toastFor } from './auto-sleep-toast';

describe('toastFor', () => {
  test('says the owner sentence, lowercase, as a local card', () => {
    const toast = toastFor({ session_id: 'ses_1', session_uuid: 'u1', session_name: 'api', idle_minutes: 60 }, 5);
    expect(toast).not.toBeNull();
    expect(toast?.body).toBe('slept api after 60 min idle');
    expect(toast?.local).toBe(true);
    expect(toast?.session_id).toBeNull();
    expect(toast?.id).toBe('autoslept:u1:5');
  });

  test('a frame with no session raises nothing', () => {
    expect(toastFor({ session_name: 'api', idle_minutes: 60 })).toBeNull();
  });

  test('a frame with no name falls back to the session id, never blank', () => {
    expect(toastFor({ session_id: 'ses_9', idle_minutes: 30 })?.body).toBe('slept ses_9 after 30 min idle');
  });
});

describe('coffee glyph', () => {
  test('has a cup and three steam wisps the stylesheets can find', () => {
    const elements = (GLYPHS as Record<string, Array<Record<string, string>>>).coffee ?? [];
    const steam = elements.filter((e) => (e.class ?? '').includes('kaw-steam'));
    expect(steam.length).toBe(3);
    expect(elements.length).toBe(5);
    expect(glyphSvg('coffee', 13)).toContain('class="kaw-steam kaw-steam-2"');
  });
});
