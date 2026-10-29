import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const PAGE = fileURLToPath(new URL('./index.html', import.meta.url));

describe('the widget harness page', () => {
  it('loads the shared visibility observer before the harness module', () => {
    const html = fs.readFileSync(PAGE, 'utf8');
    const observer = html.indexOf('/static/js/visibility-observer.js');
    expect(observer, 'visibility-observer.js is not loaded').toBeGreaterThan(-1);
    expect(observer).toBeLessThan(html.indexOf('src="./main.ts"'));
  });

  it('goes red when the script is absent', () => {
    const html = fs.readFileSync(PAGE, 'utf8').replace('/static/js/visibility-observer.js', '/static/js/other.js');
    expect(html.indexOf('/static/js/visibility-observer.js')).toBe(-1);
  });
});
