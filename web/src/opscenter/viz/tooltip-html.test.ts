import { expect, test } from 'vitest';
import { escapeHtml } from './tooltip-html';

test('markup in a label is neutralised', () => {
  expect(escapeHtml('<img src=x onerror="a">')).toBe('&lt;img src=x onerror=&quot;a&quot;&gt;');
  expect(escapeHtml("a & b's")).toBe('a &amp; b&#39;s');
});

test('absent values read as empty and plain text is unchanged', () => {
  expect(escapeHtml(null)).toBe('');
  expect(escapeHtml(undefined)).toBe('');
  expect(escapeHtml('api / opus')).toBe('api / opus');
  expect(escapeHtml(7)).toBe('7');
});
