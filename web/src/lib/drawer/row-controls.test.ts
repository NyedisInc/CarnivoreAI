/** @vitest-environment jsdom */
import { describe, expect, it } from 'vitest';
import { escAttr, escHtml, pinLegendHtml } from './row-controls';

describe('row controls (port of session-sidebar-row-controls.js)', () => {
  it('escAttr closes every way out of a double-quoted attribute', () => {
    expect(escAttr('a" onmouseover=alert(1) x="b')).toBe('a&quot; onmouseover=alert(1) x=&quot;b');
    expect(escAttr(`&<>'`)).toBe('&amp;&lt;&gt;&#39;');
    expect(escAttr(null)).toBe('');
    expect(escAttr(undefined)).toBe('');
  });
  it('escHtml escapes text and the quote', () => {
    expect(escHtml('<b>"x"</b>')).toBe('&lt;b&gt;&quot;x&quot;&lt;/b&gt;');
    expect(escHtml(null)).toBe('');
  });
  it('pinLegendHtml draws the pinned and tilted pin swatches from pinAttrs, inert', () => {
    const on = pinLegendHtml(true);
    const off = pinLegendHtml(false);
    expect(on).toContain('aria-pressed="true"');
    expect(off).toContain('aria-pressed="false"');
    expect(on).toContain('class="session-sidebar-row-pin"');
    expect(on).toMatch(/ disabled /);
    expect(on).toContain('aria-hidden="true"');
    expect(on).toContain('<svg');
  });
});
