import { allowedHref, parseMarkdown, type Block } from '../../opscenter/cells/notes/markdown';

export const GUIDE_COMPONENTS = ['open-legend', 'feature-index', 'mcp-tools'] as const;
export type GuideComponentName = (typeof GUIDE_COMPONENTS)[number];

export interface Hotspot {
    x: number;
    y: number;
    target: string;
    title: string;
    text: string;
}

export interface LegendRow {
    state: string;
    hue: string;
    text: string;
}

export type GuideBlock =
    | { kind: 'md'; blocks: Block[] }
    | { kind: 'shot'; feature: string; file: string; alt: string; hotspots: Hotspot[] }
    | { kind: 'legend'; rows: LegendRow[] }
    | { kind: 'component'; name: GuideComponentName };

export interface GuideDoc {
    title: string;
    blocks: GuideBlock[];
    /* could not be read */
    errors: string[];
}

const FRAGMENT = /^#[a-z0-9][a-z0-9/_-]*$/;

export function guideLinkAllowed(href: string): boolean {
    const value = href.trim();
    return FRAGMENT.test(value) || allowedHref(value);
}

export function isFragmentTarget(target: string): boolean {
    return FRAGMENT.test(target);
}

const FENCE = /^\s{0,3}```/;
const BLOCK_OPEN = /^:::(shot|legend)[ \t]*(.*)$/;
const BLOCK_CLOSE = /^:::[ \t]*$/;
const COMPONENT = /^::([a-z][a-z-]*)[ \t]*$/;
const PICTURE = /^!\[([^\]]*)\]\(feature:([a-z0-9][a-z0-9-]*)\/([A-Za-z0-9][A-Za-z0-9._-]*\.(?:png|webp|gif|svg))\)[ \t]*$/;
const SHOT_SOURCE = /^([a-z0-9][a-z0-9-]*)\/([A-Za-z0-9][A-Za-z0-9._-]*\.(?:png|webp|gif|svg))$/;
const LIST_ITEM = /^-\s+(.*)$/;

function parseHotspot(rest: string): Hotspot | null {
    const parts = rest.split('|').map((p) => p.trim());
    if (parts.length < 4) return null;
    const [pos, target, title, ...words] = parts as [string, string, string, ...string[]];
    const at = /^(\d{1,3}(?:\.\d+)?)\s+(\d{1,3}(?:\.\d+)?)$/.exec(pos);
    if (!at) return null;
    const x = Number(at[1]);
    const y = Number(at[2]);
    const text = words.join(' | ');
    if (x > 100 || y > 100 || !isFragmentTarget(target) || !title || !text) return null;
    return { x, y, target, title, text };
}

function parseLegendRow(rest: string): LegendRow | null {
    const parts = rest.split('|').map((p) => p.trim());
    if (parts.length < 3) return null;
    const [state, hue, ...words] = parts as [string, string, ...string[]];
    const text = words.join(' | ');
    if (!/^[a-z_]+$/.test(state) || !hue || !text) return null;
    return { state, hue, text };
}

export function parseGuide(source: string): GuideDoc {
    const lines = source.replace(/\r\n?/g, '\n').split('\n');
    const blocks: GuideBlock[] = [];
    const errors: string[] = [];
    let title = '';
    let buffer: string[] = [];
    let inFence = false;

    const flush = (): void => {
        const text = buffer.join('\n');
        buffer = [];
        if (!text.trim()) return;
        blocks.push({ kind: 'md', blocks: parseMarkdown(text, guideLinkAllowed) });
    };

    for (let at = 0; at < lines.length; at += 1) {
        const line = lines[at] as string;
        if (FENCE.test(line)) {
            inFence = !inFence;
            buffer.push(line);
            continue;
        }
        if (inFence) {
            buffer.push(line);
            continue;
        }
        const heading = /^#\s+(.+?)\s*$/.exec(line);
        if (heading && !title) {
            title = heading[1] as string;
            continue;
        }
        const open = BLOCK_OPEN.exec(line);
        if (open) {
            flush();
            const body: string[] = [];
            at += 1;
            while (at < lines.length && !BLOCK_CLOSE.test(lines[at] as string)) {
                body.push(lines[at] as string);
                at += 1;
            }
            if (at >= lines.length) errors.push(`unterminated :::${open[1]} block`);
            const block = open[1] === 'shot' ? readShot((open[2] as string).trim(), body, errors) : readLegend(body, errors);
            if (block) blocks.push(block);
            continue;
        }
        const component = COMPONENT.exec(line);
        if (component) {
            flush();
            const name = component[1] as string;
            if ((GUIDE_COMPONENTS as readonly string[]).includes(name)) blocks.push({ kind: 'component', name: name as GuideComponentName });
            else errors.push(`unknown component ::${name}`);
            continue;
        }
        const picture = PICTURE.exec(line);
        if (picture) {
            flush();
            blocks.push({ kind: 'shot', feature: picture[2] as string, file: picture[3] as string, alt: picture[1] as string, hotspots: [] });
            continue;
        }
        buffer.push(line);
    }
    flush();
    if (!title) errors.push('no title heading');
    return { title, blocks, errors };
}

function readShot(ref: string, body: string[], errors: string[]): GuideBlock | null {
    const source = SHOT_SOURCE.exec(ref);
    if (!source) {
        errors.push(`bad shot source "${ref}"`);
        return null;
    }
    let alt = '';
    const hotspots: Hotspot[] = [];
    for (const raw of body) {
        const line = raw.trim();
        if (!line) continue;
        if (line.startsWith('alt:')) {
            alt = line.slice(4).trim();
            continue;
        }
        const item = LIST_ITEM.exec(line);
        const mark = item ? parseHotspot(item[1] as string) : null;
        if (mark) hotspots.push(mark);
        else errors.push(`bad mark line "${line}"`);
    }
    if (!alt) errors.push(`shot ${ref} has no alt text`);
    return { kind: 'shot', feature: source[1] as string, file: source[2] as string, alt, hotspots };
}

function readLegend(body: string[], errors: string[]): GuideBlock {
    const rows: LegendRow[] = [];
    for (const raw of body) {
        const line = raw.trim();
        if (!line) continue;
        const item = LIST_ITEM.exec(line);
        const row = item ? parseLegendRow(item[1] as string) : null;
        if (row) rows.push(row);
        else errors.push(`bad legend line "${line}"`);
    }
    return { kind: 'legend', rows };
}
