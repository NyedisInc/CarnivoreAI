import { describe, expect, test } from 'vitest';
import { dispositionFilename } from './auth.svelte';

describe('dispositionFilename', () => {
  test('prefers the RFC 6266 UTF-8 name over the ASCII fallback', () => {
    expect(dispositionFilename(`attachment; filename="r_sum_.txt"; filename*=UTF-8''r%C3%A9sum%C3%A9.txt`)).toBe('résumé.txt');
  });
  test('falls back to the plain name, also when the escape is malformed', () => {
    expect(dispositionFilename('attachment; filename="report.pdf"')).toBe('report.pdf');
    expect(dispositionFilename(`attachment; filename="x.txt"; filename*=UTF-8''%E0%A4%A`)).toBe('x.txt');
    expect(dispositionFilename('attachment')).toBeUndefined();
  });
});
