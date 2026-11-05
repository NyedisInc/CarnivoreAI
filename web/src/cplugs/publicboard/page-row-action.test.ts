/** @vitest-environment jsdom */
import { describe, expect, it } from 'vitest';
import { boardSlugOfPage } from './page-row-action';

const page = (src: string | null, key = 'app:/static/popout.html?x=1') => ({ key, src, title: 't' });
const BASE = '/static/popout.html?tab=reviewboard';

describe('boardSlugOfPage', () => {
  it('reads the slug of a board page', () => {
    expect(boardSlugOfPage(page(`${BASE}&board=20261013-nav&rev=r2`))).toBe('20261013-nav');
  });

  it('decodes an encoded slug', () => {
    expect(boardSlugOfPage(page(`${BASE}&board=20261013%2Dnav%20two`))).toBe('20261013-nav two');
  });

  it('refuses a page on any other path, even with the right query', () => {
    expect(boardSlugOfPage(page('/static/other.html?tab=reviewboard&board=a'))).toBeNull();
    expect(boardSlugOfPage(page('/static/popout.html.evil?tab=reviewboard&board=a'))).toBeNull();
  });

  it('refuses another tab, and a page with no board', () => {
    expect(boardSlugOfPage(page('/static/popout.html?tab=flow&board=a'))).toBeNull();
    expect(boardSlugOfPage(page(BASE))).toBeNull();
  });

  it('never lets a fragment into the slug or the query', () => {
    expect(boardSlugOfPage(page(`${BASE}&board=a#&board=b`))).toBe('a');
    expect(boardSlugOfPage(page('/static/popout.html#?tab=reviewboard&board=a'))).toBeNull();
  });

  it('reads a plus as the board page does: a space, not a literal plus', () => {
    expect(boardSlugOfPage(page(`${BASE}&board=a+b`))).toBe('a b');
    expect(boardSlugOfPage(page(`${BASE}&board=a%2Bb`))).toBe('a+b');
  });

  it('refuses a slug that climbs a path', () => {
    expect(boardSlugOfPage(page(`${BASE}&board=..%2Fsecret`))).toBeNull();
    expect(boardSlugOfPage(page(`${BASE}&board=a%5Cb`))).toBeNull();
    expect(boardSlugOfPage(page(`${BASE}&board=..`))).toBeNull();
  });

  it('falls back to the key when the page has no src, and refuses an unparseable address', () => {
    expect(boardSlugOfPage(page(null, `app:${BASE}&board=a`))).toBe('a');
    expect(boardSlugOfPage(page('http://[bad', 'k'))).toBeNull();
  });
});
