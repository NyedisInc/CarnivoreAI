import { describe, expect, test } from 'vitest';
import { guideLinkAllowed, parseGuide } from './guide-parse';

describe('parseGuide', () => {
    test('takes the title from the first heading and keeps the rest as markdown', () => {
        const doc = parseGuide('# my title\n\nhello **there**\n\n1. one\n2. two\n');
        expect(doc.title).toBe('my title');
        expect(doc.errors).toEqual([]);
        expect(doc.blocks).toHaveLength(1);
        const md = doc.blocks[0];
        expect(md?.kind).toBe('md');
        if (md?.kind === 'md') expect(md.blocks.map((b) => b.kind)).toEqual(['paragraph', 'list']);
    });

    test('reads no directive inside a code fence, and no title either', () => {
        const doc = parseGuide('# t\n\n```\n# not a title\n::open-legend\n:::shot a/b.png\n```\n');
        expect(doc.title).toBe('t');
        expect(doc.errors).toEqual([]);
        expect(doc.blocks).toHaveLength(1);
        expect(doc.blocks[0]?.kind).toBe('md');
    });

    test('reads a shot with marks', () => {
        const doc = parseGuide(
            ['# t', ':::shot user-guide/home.png', 'alt: the home screen', '- 12 8.5 | #projects | projects | the list of projects', '- 50 50 | #settings/appearance | look | pipes | inside are kept', ':::'].join('\n'),
        );
        expect(doc.errors).toEqual([]);
        const shot = doc.blocks[0];
        expect(shot).toMatchObject({ kind: 'shot', feature: 'user-guide', file: 'home.png', alt: 'the home screen' });
        if (shot?.kind !== 'shot') throw new Error('not a shot');
        expect(shot.hotspots).toEqual([
            { x: 12, y: 8.5, target: '#projects', title: 'projects', text: 'the list of projects' },
            { x: 50, y: 50, target: '#settings/appearance', title: 'look', text: 'pipes | inside are kept' },
        ]);
    });

    test('names and drops every bad directive line', () => {
        const doc = parseGuide(
            [
                '# t',
                ':::shot no-slash',
                ':::',
                ':::shot a/b.png',
                'alt: ok',
                '- 101 5 | #projects | t | x',
                '- 5 5 | javascript:alert(1) | t | x',
                '- 5 5 | https://example.com | t | x',
                '- 5 | #projects | t | x',
                ':::',
                '::no-such-thing',
            ].join('\n'),
        );
        expect(doc.errors.length).toBe(6);
        expect(doc.errors.join('\n')).toMatch(/bad shot source/);
        expect(doc.errors.join('\n')).toMatch(/unknown component/);
        const shot = doc.blocks.find((b) => b.kind === 'shot');
        expect(shot && shot.kind === 'shot' ? shot.hotspots : ['x']).toEqual([]);
    });

    test('a shot with no alt text is an error, an unclosed block is an error, a missing title is an error', () => {
        expect(parseGuide('# t\n:::shot a/b.png\n- 5 5 | #home | t | x\n:::').errors.join()).toMatch(/no alt/);
        expect(parseGuide('# t\n:::legend\n- working | green | x').errors.join()).toMatch(/unterminated/);
        expect(parseGuide('just text').errors.join()).toMatch(/no title/);
    });

    test('reads the legend and the components', () => {
        const doc = parseGuide('# t\n:::legend\n- working | green | doing tool work\n:::\n::feature-index\n::open-legend');
        expect(doc.errors).toEqual([]);
        expect(doc.blocks[0]).toEqual({ kind: 'legend', rows: [{ state: 'working', hue: 'green', text: 'doing tool work' }] });
        expect(doc.blocks.slice(1)).toEqual([
            { kind: 'component', name: 'feature-index' },
            { kind: 'component', name: 'open-legend' },
        ]);
    });

    test('a picture line is a shot with no marks; only feature images count', () => {
        const doc = parseGuide('# t\n![alt words](feature:user-guide/home.png)\n![x](https://example.com/a.png)');
        expect(doc.blocks[0]).toEqual({ kind: 'shot', feature: 'user-guide', file: 'home.png', alt: 'alt words', hotspots: [] });
        expect(doc.blocks[1]?.kind).toBe('md');
    });

    test('raw html stays text in the tree', () => {
        const doc = parseGuide('# t\n\n<script>alert(1)</script> and <img src=x onerror=alert(1)>');
        const md = doc.blocks[0];
        if (md?.kind !== 'md') throw new Error('not markdown');
        expect(JSON.stringify(md.blocks)).toContain('<script>alert(1)</script>');
    });
});

describe('guideLinkAllowed', () => {
    test('allows page fragments, https and mailto; nothing else', () => {
        for (const ok of ['#projects', '#docs/wrappers', '#settings/appearance', 'https://example.com', 'mailto:a@b.co']) expect(guideLinkAllowed(ok), ok).toBe(true);
        for (const bad of ['javascript:alert(1)', 'data:text/html,x', '//evil.example', '#', '#Bad Frag', '/relative', '#a b']) expect(guideLinkAllowed(bad), bad).toBe(false);
    });
});
