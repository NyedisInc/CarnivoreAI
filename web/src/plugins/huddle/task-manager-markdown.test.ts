/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { parseMarkdown, parseInline, safeHref } from './task-manager-markdown';
import TaskManagerMarkdown from './TaskManagerMarkdown.svelte';

let handle: ReturnType<typeof mount> | null = null;
let host: HTMLElement | null = null;

function draw(text: string): HTMLElement {
  host = document.createElement('div');
  document.body.append(host);
  handle = mount(TaskManagerMarkdown, { target: host, props: { text } });
  flushSync();
  return host;
}

afterEach(() => {
  if (handle) void unmount(handle);
  host?.remove();
  handle = null;
  host = null;
});

describe('huddle markdown parser', () => {
  test('paragraphs and line breaks', () => {
    const [p] = parseMarkdown('one\ntwo\n\nthree');
    expect(p).toMatchObject({ t: 'paragraph' });
    const el = draw('one\ntwo\n\nthree');
    expect(el.querySelectorAll('p')).toHaveLength(2);
    expect(el.querySelector('p br')).not.toBeNull();
  });

  test('bold, italic and inline code', () => {
    expect(parseInline('a **b** *c* `d`').map((n) => n.t)).toEqual(['text', 'strong', 'text', 'em', 'text', 'code']);
    const el = draw('a **b** *c* `d *x*`');
    expect(el.querySelector('strong')?.textContent).toBe('b');
    expect(el.querySelector('em')?.textContent).toBe('c');
    expect(el.querySelector('code')?.textContent).toBe('d *x*');
  });

  test('a lone star and a math star stay text', () => {
    const el = draw('2 * 3 * 4');
    expect(el.querySelector('em')).toBeNull();
    expect(el.textContent).toBe('2 * 3 * 4');
  });

  test('fenced code keeps its text and does not parse inside', () => {
    const el = draw('```ts\nconst a = **1**;\n  x\n```');
    expect(el.querySelector('pre code')?.textContent).toBe('const a = **1**;\n  x');
    expect(el.querySelector('strong')).toBeNull();
  });

  test('headings, bullets, numbers, one nested level', () => {
    const el = draw('# Big\n## Small\n- a\n  - a1\n  - a2\n- b\n\n1. one\n2. two');
    expect(el.querySelectorAll('[role=heading]')).toHaveLength(2);
    expect(el.querySelectorAll('ul')).toHaveLength(2);
    expect(el.querySelectorAll('ul > li > ul > li')).toHaveLength(2);
    expect(el.querySelectorAll('ol > li')).toHaveLength(2);
  });

  test('links: http and https open in a new tab with noopener', () => {
    const el = draw('see [docs](https://example.com/a) and http://example.org/x.');
    const links = [...el.querySelectorAll('a')];
    expect(links.map((a) => a.getAttribute('href'))).toEqual(['https://example.com/a', 'http://example.org/x']);
    for (const a of links) {
      expect(a.target).toBe('_blank');
      expect(a.rel).toContain('noopener');
    }
    expect(el.textContent).toContain('x.');
  });

  test('javascript: and data: links are refused and stay text', () => {
    expect(safeHref('javascript:alert(1)')).toBeNull();
    expect(safeHref('data:text/html,hi')).toBeNull();
    const el = draw('[x](javascript:alert(1)) [y](data:text/html,hi)');
    expect(el.querySelector('a')).toBeNull();
    expect(el.textContent).toContain('[x](javascript:alert(1))');
  });

  test('HTML in the input is literal text, never an element', () => {
    const el = draw('<img src=x onerror=alert(1)> <script>boom()</script> **<b>hi</b>**');
    expect(el.querySelector('img')).toBeNull();
    expect(el.querySelector('script')).toBeNull();
    expect(el.querySelector('b')).toBeNull();
    expect(el.textContent).toContain('<img src=x onerror=alert(1)>');
    expect(el.textContent).toContain('<script>boom()</script>');
  });

  test('a pipe table: numeric columns right aligned, in a scroll box', () => {
    const el = draw('| name | count | pct |\n|---|---|:---:|\n| a | 1,200 | 5% |\n| b | 30 | 10% |');
    expect(el.querySelector('[data-task-manager-md-table]')).not.toBeNull();
    expect(el.querySelectorAll('thead th')).toHaveLength(3);
    expect(el.querySelectorAll('tbody tr')).toHaveLength(2);
    expect(el.querySelectorAll('th')[0]?.className).toContain('hmd-cell--left');
    expect(el.querySelectorAll('th')[1]?.className).toContain('hmd-cell--right');
    expect(el.querySelectorAll('td')[1]?.className).toContain('hmd-cell--right');
    expect(el.querySelectorAll('td')[2]?.className).toContain('hmd-cell--center');
  });

  test('a mixed column is not right aligned', () => {
    const [t] = parseMarkdown('| a |\n|---|\n| 1 |\n| x |');
    expect(t).toMatchObject({ t: 'table', align: ['left'] });
  });

  test('a malformed table falls back to text', () => {
    for (const bad of ['| a | b |\n|---|\n| 1 | 2 |', '| a | b |\n|---|---|\n| 1 |', '| a | b |\n| 1 | 2 |']) {
      const el = draw(bad);
      expect(el.querySelector('table')).toBeNull();
      expect(el.textContent).toContain('| a | b |');
      unmount(handle as ReturnType<typeof mount>);
      handle = null;
      host?.remove();
    }
  });

  test('a kv block is an aligned label/value grid', () => {
    const el = draw('```kv\nstatus: **done**\nbranch: huddle-x\n```');
    const dl = el.querySelector('[data-task-manager-md-kv]');
    expect(dl).not.toBeNull();
    expect([...el.querySelectorAll('dt')].map((d) => d.textContent)).toEqual(['status', 'branch']);
    expect(el.querySelector('dd strong')?.textContent).toBe('done');
  });

  test('a kv block with a non key: value line is an ordinary code block', () => {
    const el = draw('```kv\nstatus: ok\njust words\n```');
    expect(el.querySelector('dl')).toBeNull();
    expect(el.querySelector('pre')).not.toBeNull();
  });

  test('text past the cap is one plain paragraph', () => {
    const [p] = parseMarkdown(`**${'x'.repeat(20001)}**`);
    expect(p).toMatchObject({ t: 'paragraph' });
  });
});

describe('ordered list numbering', () => {
  test('items with nested bullets stay one list', () => {
    const blocks = parseMarkdown('1. **first.** text\n   - nested a\n   - nested b\n2. **second.** text\n3. third');
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ t: 'list', ordered: true, start: 1 });
    expect((blocks[0] as { items: unknown[] }).items).toHaveLength(3);
  });

  test('one blank line between items keeps one list', () => {
    const blocks = parseMarkdown('1. a\n\n2. b\n\n3. c');
    expect(blocks).toHaveLength(1);
    const el = draw('1. a\n\n2. b\n\n3. c');
    expect(el.querySelectorAll('ol')).toHaveLength(1);
    expect(el.querySelectorAll('ol > li')).toHaveLength(3);
  });

  test('the first written number sets start', () => {
    expect(parseMarkdown('7. a\n8. b')[0]).toMatchObject({ ordered: true, start: 7 });
    const el = draw('7. a\n8. b');
    expect(el.querySelector('ol')?.getAttribute('start')).toBe('7');
  });

  test('a blank line before a different list kind ends the list', () => {
    expect(parseMarkdown('1. a\n\n- b')).toHaveLength(2);
  });
});
