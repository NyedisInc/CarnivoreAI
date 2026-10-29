import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';
import { postFold } from './task-manager-posts';
import { parseInline, parseMarkdown, type MdBlock } from './task-manager-markdown';
import { clipBlocks } from './task-manager-markdown-clip';

const seen = (blocks: MdBlock[]): string => JSON.stringify(blocks).match(/"v":"[^"]*"/g)?.join('') ?? '';
const folded = (text: string): MdBlock[] => { const f = postFold(text); return clipBlocks(parseMarkdown(f.folded), f.limit, f.more); };

const src = (name: string): string => readFileSync(`src/cplugs/huddle/${name}`, 'utf8');
const NARROW = /@container hdr \(max-width: 22rem\) \{[^]*?grid-column:\s*1 \/ -1/;

describe('A: a narrow row gives every block its full width', () => {
  test('the row is the container and its own blocks span all columns when narrow', () => {
    const row = src('TaskManagerRow.svelte');
    expect(row).toMatch(/container:\s*hdr \/ inline-size/);
    expect(row).toMatch(NARROW);
    expect(row).toMatch(/\.hdr-line \{[^}]*flex-wrap: wrap/);
  });

  test.each(['TaskManagerRowPeek.svelte', 'HuddleReview.svelte'])('%s spans the row when narrow', (file) => {
    expect(src(file)).toMatch(NARROW);
  });

  test('the toolbar and the view keys can shrink instead of widening the drawer', () => {
    expect(src('HuddleBody.svelte')).toMatch(/\.hd-bar \{\s*display: flex;\s*flex-wrap: wrap/);
    expect(src('HuddleViewSwitch.svelte')).toMatch(/flex: 0 1 auto;\s*min-width: 0/);
  });
});

describe('B: the folded text never keeps a half-open bold pair', () => {
  test('a bold pair that closes on a later line is not a lead; the fold keeps it bold', () => {
    const post = postFold(`**Ten installs are frozen\nwhile the bundle rebuilds**\n${'details '.repeat(50)}`);
    expect(post.lead).toBe(false);
    const tree = folded(`**Ten installs are frozen\nwhile the bundle rebuilds**\n${'details '.repeat(50)}`);
    expect(JSON.stringify(tree)).toContain('"t":"strong"');
    expect(seen(tree)).not.toContain('*');
  });

  test('a cut inside a pair keeps the bold words up to the cut, ellipsis last, no marker', () => {
    const tree = folded(`${'word '.repeat(40)}**${'bold '.repeat(30)}**`);
    expect(seen(tree)).not.toContain('*');
    expect(JSON.stringify(tree)).toContain('"t":"strong"');
    expect(seen(tree).endsWith('"v":"…"')).toBe(true);
  });

  test('the fold never slices inside a line: the folded text is whole source lines', () => {
    const text = `${'word '.repeat(40)}**${'bold '.repeat(30)}**`;
    expect(postFold(text)).toMatchObject({ foldable: true, folded: text, limit: 240, more: true });
    expect(postFold('short **bold** line')).toMatchObject({ foldable: false, folded: 'short **bold** line', limit: 0 });
  });

  test('a double-escaped poster (literal backslash-n) is shown as written, never rewritten', () => {
    const text = 'one\\ntwo \\"q\\"';
    expect(postFold(text).full).toBe(text);
    const flat = JSON.stringify(parseMarkdown(text));
    expect(flat).toContain('one\\\\ntwo');
  });
});

describe('B2: stars the renderer must honor', () => {
  const strong = (t: string) => JSON.stringify(parseInline(t));

  test('***bold italic*** is bold and italic with no star left over', () => {
    expect(strong('***blah***')).toBe('[{"t":"strong","c":[{"t":"em","c":[{"t":"text","v":"blah"}]}]}]');
    expect(strong('*** blah ***')).toBe('[{"t":"strong","c":[{"t":"em","c":[{"t":"text","v":"blah"}]}]}]');
  });

  test('a bold pair at the very start of a line, and before more text, is bold', () => {
    expect(strong('**bold** rest')).toBe('[{"t":"strong","c":[{"t":"text","v":"bold"}]},{"t":"text","v":" rest"}]');
    expect(JSON.stringify(parseMarkdown('**Lead.**\nbody'))).toContain('"t":"strong"');
  });

  test('a folded cut inside a run of three stars keeps it bold italic, never leaving a star', () => {
    const tree = folded(`***blah ${'word '.repeat(70)}***\nmore`);
    expect(seen(tree)).not.toContain('*');
    expect(JSON.stringify(tree)).toContain('"t":"strong","c":[{"t":"em"');
  });
});
