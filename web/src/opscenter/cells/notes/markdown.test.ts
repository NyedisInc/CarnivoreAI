/** @vitest-environment jsdom */
import { describe, expect, it } from 'vitest';

import { allowedHref, parseInline, parseMarkdown, renderMarkdown } from './markdown';

function render(source: string): HTMLElement {
  const host = document.createElement('div');
  host.appendChild(renderMarkdown(source, document));
  return host;
}

function tags(source: string): string[] {
  return Array.from(render(source).querySelectorAll('*')).map((el) => el.tagName.toLowerCase());
}

describe('the block grammar', () => {
  it('reads the six heading levels and nothing beyond them', () => {
    expect(tags('# one')).toEqual(['h1']);
    expect(tags('###### six')).toEqual(['h6']);
    expect(tags('####### seven')).toEqual(['p']);
    expect(render('####### seven').textContent).toBe('####### seven');
  });

  it('needs a space after the hashes, so a tag is not a heading', () => {
    expect(tags('#1 priority')).toEqual(['p']);
  });

  it('builds both kinds of list', () => {
    expect(tags('- a\n- b')).toEqual(['ul', 'li', 'li']);
    expect(tags('1. a\n2. b')).toEqual(['ol', 'li', 'li']);
    expect(render('1. a\n2. b').textContent).toBe('ab');
  });

  it('keeps a fenced block literal, markers and all', () => {
    const host = render('```\n**not bold**\n# not a heading\n```');
    expect(tags('```\nx\n```')).toEqual(['pre', 'code']);
    expect(host.querySelector('code')?.textContent).toBe('**not bold**\n# not a heading');
    expect(host.querySelector('strong')).toBeNull();
  });

  it('runs an unclosed fence to the end, which is what typing one looks like', () => {
    expect(render('```\nstill typing').querySelector('code')?.textContent).toBe('still typing');
  });

  it('draws a rule and a quote', () => {
    expect(tags('---')).toEqual(['hr']);
    expect(tags('--')).toEqual(['p']);
    expect(tags('> quoted')).toEqual(['blockquote']);
    expect(render('> quoted').textContent).toBe('quoted');
  });

  it('keeps a single newline inside a paragraph as a line break', () => {
    expect(tags('one\ntwo')).toEqual(['p', 'br']);
  });

  it('separates paragraphs on a blank line', () => {
    expect(tags('one\n\ntwo')).toEqual(['p', 'p']);
  });

  it('renders an empty note as nothing at all', () => {
    expect(parseMarkdown('')).toEqual([]);
    expect(render('').childNodes.length).toBe(0);
  });
});

describe('the inline grammar', () => {
  it('keeps intraword underscores and still reads _emphasis_ at word boundaries', () => {
    expect(render('call swarm_ask then tests/test_hello.py').textContent).toBe('call swarm_ask then tests/test_hello.py');
    expect(tags('call swarm_ask then tests/test_hello.py')).toEqual(['p']);
    expect(tags('a _word_ here')).toEqual(['p', 'em']);
    expect(tags('snake_case and _it_.')).toEqual(['p', 'em']);
    expect(render('`a_b_c`').textContent).toBe('a_b_c');
  });

  it('reads bold, italic and inline code', () => {
    expect(tags('**b**')).toEqual(['p', 'strong']);
    expect(tags('*i*')).toEqual(['p', 'em']);
    expect(tags('_i_')).toEqual(['p', 'em']);
    expect(tags('`c`')).toEqual(['p', 'code']);
    expect(render('**b**').textContent).toBe('b');
  });

  it('lets inline code win over every other marker', () => {
    const host = render('`**not bold**`');
    expect(host.querySelector('code')?.textContent).toBe('**not bold**');
    expect(host.querySelector('strong')).toBeNull();
  });

  it('treats an unpaired marker as the character it is', () => {
    expect(render('2 * 3 = 6').textContent).toBe('2 * 3 = 6');
    expect(tags('2 * 3 = 6')).toEqual(['p']);
    expect(render('**unclosed').textContent).toBe('**unclosed');
  });
});

describe('what a note may never render', () => {
  it('renders a script tag as the text it is', () => {
    const source = '<img src=x onerror=alert(1)>\n\n<script>alert(2)</script>';
    const host = render(source);
    expect(host.querySelector('script')).toBeNull();
    expect(host.querySelector('img')).toBeNull();
    expect(host.textContent).toContain('<script>alert(2)</script>');
    expect(host.textContent).toContain('<img src=x onerror=alert(1)>');
  });

  it('refuses every scheme but http, https and mailto', () => {
    expect(allowedHref('http://a.test')).toBe(true);
    expect(allowedHref('https://a.test')).toBe(true);
    expect(allowedHref('mailto:a@b.test')).toBe(true);
    expect(allowedHref('javascript:alert(1)')).toBe(false);
    expect(allowedHref('JavaScript:alert(1)')).toBe(false);
    expect(allowedHref('data:text/html,<script>')).toBe(false);
    expect(allowedHref('//evil.test/x')).toBe(false);
    expect(allowedHref('/relative')).toBe(false);
  });

  it('prints a refused link as the characters the author typed', () => {
    const host = render('[click](javascript:alert(1))');
    expect(host.querySelector('a')).toBeNull();
    expect(host.textContent).toBe('[click](javascript:alert(1))');
  });

  it('builds an allowed link with the two attributes that make it safe', () => {
    const link = render('[docs](https://a.test/x)').querySelector('a');
    expect(link?.getAttribute('href')).toBe('https://a.test/x');
    expect(link?.getAttribute('rel')).toBe('noopener noreferrer');
    expect(link?.textContent).toBe('docs');
  });

  it('keeps the parse pure, so the grammar is provable with no document', () => {
    expect(parseInline('a `b` c')).toEqual([
      { kind: 'text', text: 'a ' },
      { kind: 'code', text: 'b' },
      { kind: 'text', text: ' c' },
    ]);
  });
});

describe('a caller-supplied link filter', () => {
  const fragmentsOnly = (href: string): boolean => /^#[a-z]+$/.test(href);

  it('decides which targets become links, in the parse and again in the build', () => {
    const doc = document.implementation.createHTMLDocument('x');
    const out = renderMarkdown('[in](#page) [out](https://example.com)', doc, fragmentsOnly);
    const links = [...out.querySelectorAll('a')];
    expect(links.map((a) => a.getAttribute('href'))).toEqual(['#page']);
    expect(links[0]?.getAttribute('target')).toBeNull();
    expect(out.textContent).toContain('[out](https://example.com)');
  });

  it('the default filter still refuses a fragment and opens web links away', () => {
    const doc = document.implementation.createHTMLDocument('x');
    const out = renderMarkdown('[in](#page) [out](https://example.com)', doc);
    expect([...out.querySelectorAll('a')].map((a) => a.getAttribute('target'))).toEqual(['_blank']);
  });
});
