/** @vitest-environment jsdom */
import { describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import TaskManagerMarkdown from './TaskManagerMarkdown.svelte';
import { parseLine, parseMarkdown, plainOf } from './task-manager-markdown';
import { clipInline } from './task-manager-markdown-clip';

describe('code spans are literal', () => {
  test.each(['***x***', '**a**', 'a*b*c'])('`%s` keeps every character', (src) => {
    const nodes = parseLine('see `' + src + '` here');
    expect(nodes.find((n) => n.t === 'code')).toEqual({ t: 'code', v: src });
    const blocks = parseMarkdown('- cut. `' + src + '` renders as bold italic.');
    expect(JSON.stringify(blocks)).toContain(JSON.stringify({ t: 'code', v: src }));
  });

  test('the review description of item 222 keeps its code span literal', () => {
    const src = '**Markdown everywhere in the huddle**\n- Rows, titles, the latest line and every field in the answer popup now use one markdown renderer.\n- A cut line is trimmed after rendering, so bold, italic and code hold right up to the ellipsis. `***x***` renders as bold italic.\n\n**One bubble base**\n- All eight message types (info, look, question, answer, claude, owner, approval, review) draw from one base.\n- A new type is one entry in the `BUBBLES` registry. The style guide shows every type.\n\nLive in 1.15.1. A tick pushes it.';
    expect(JSON.stringify(parseMarkdown(src))).toContain('{"t":"code","v":"***x***"}');
  });

  test('a code span inside bold stays literal', () => {
    const nodes = parseLine('**keep `***x***` here**');
    expect(nodes).toHaveLength(1);
    const strong = nodes[0] as { t: string; c: { t: string; v?: string }[] };
    expect(strong.t).toBe('strong');
    expect(strong.c.find((n) => n.t === 'code')).toEqual({ t: 'code', v: '***x***' });
  });

  test('a fold that cuts inside a code span keeps the span literal', () => {
    const nodes = parseLine('go `***x***` on');
    const cut = clipInline(nodes, 6, true).nodes;
    const code = cut.find((n) => n.t === 'code') as { v: string } | undefined;
    expect(code).toBeDefined();
    expect('***x***'.startsWith(code!.v.replace(/…$/, ''))).toBe(true);
    expect(plainOf(cut)).not.toMatch(/\*{7}/);
  });

  test('the drawn code pill shows the literal characters in the DOM', () => {
    const host = document.createElement('div');
    document.body.append(host);
    const app = mount(TaskManagerMarkdown, { target: host, props: { text: '- a cut. `***x***` renders.\n- `a*b*c` and **bold `**a**` bold**' } });
    flushSync();
    const pills = [...host.querySelectorAll('code.hmd-code')].map((el) => el.textContent);
    expect(pills).toEqual(['***x***', 'a*b*c', '**a**']);
    unmount(app);
    host.remove();
  });
});
