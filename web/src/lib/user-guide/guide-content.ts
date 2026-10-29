import type { Block, Inline } from '../../opscenter/cells/notes/markdown';
import { parseGuide, type GuideBlock, type GuideDoc } from './guide-parse';

export interface GuideSection {
    id: string;
    title: string;
    doc: GuideDoc;
    searchText: string;
}

const SOURCES = import.meta.glob('../../../../docs/user-guide/[0-9][0-9]-*.md', {
    query: '?raw',
    import: 'default',
    eager: true,
}) as Record<string, string>;

function inlineText(runs: Inline[]): string {
    return runs
        .map((run) => {
            if (run.kind === 'text' || run.kind === 'code') return run.text;
            if (run.kind === 'break') return ' ';
            return inlineText(run.children);
        })
        .join('');
}

function blockText(block: Block): string {
    if (block.kind === 'rule') return '';
    if (block.kind === 'code') return block.text;
    if (block.kind === 'list') {
        return block.items.map((item, i) => [item, ...(block.subs[i]?.items ?? [])].map(inlineText).join(' ')).join(' ');
    }
    return inlineText(block.children);
}

function partText(block: GuideBlock): string {
    if (block.kind === 'md') return block.blocks.map(blockText).join(' ');
    if (block.kind === 'shot') return [block.alt, ...block.hotspots.flatMap((h) => [h.title, h.text])].join(' ');
    if (block.kind === 'legend') return block.rows.flatMap((r) => [r.state, r.hue, r.text]).join(' ');
    return '';
}

export function sectionText(doc: GuideDoc): string {
    return [doc.title, ...doc.blocks.map(partText)].join(' ').toLowerCase();
}

export function buildSections(sources: Record<string, string>): GuideSection[] {
    const out: GuideSection[] = [];
    for (const path of Object.keys(sources).sort()) {
        const id = /\/\d{2}-([a-z0-9-]+)\.md$/.exec(path)?.[1];
        if (!id) continue;
        const doc = parseGuide(sources[path] as string);
        out.push({ id, title: doc.title, doc, searchText: sectionText(doc) });
    }
    return out;
}

export const GUIDE_SECTIONS: readonly GuideSection[] = buildSections(SOURCES);
