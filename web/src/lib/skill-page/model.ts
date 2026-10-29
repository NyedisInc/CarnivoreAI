import { switchable, type ContextChoice } from '../skills-page/skills-model';
import type { SkillGroupRow, SkillLocationRow } from '../skills-page/skills-types';

export interface FrontEntry {
    readonly key: string;
    readonly value: string;
}

export interface SplitMd {
    readonly front: readonly FrontEntry[];
    readonly lists: Readonly<Record<string, readonly string[]>>;
    readonly body: string;
}

export const MAX_TRIGGERS = 6;

function unquote(raw: string): string {
    const text = raw.trim();
    const first = text.charAt(0);
    return text.length >= 2 && (first === '"' || first === "'") && text.endsWith(first) ? text.slice(1, -1) : text;
}

export function splitSkillMd(text: string): SplitMd {
    const lines = text.replace(/\r\n?/g, '\n').split('\n');
    if (lines[0]?.trim() !== '---') return { front: [], lists: {}, body: lines.join('\n') };
    const end = lines.findIndex((line, i) => i > 0 && line.trim() === '---');
    if (end < 0) return { front: [], lists: {}, body: lines.join('\n') };
    const front: { key: string; value: string }[] = [];
    const lists: Record<string, string[]> = {};
    let current: { key: string; value: string } | null = null;
    for (const line of lines.slice(1, end)) {
        const item = /^\s+-\s+(.*)$/.exec(line);
        if (item && current) {
            (lists[current.key] ??= []).push(unquote(item[1] ?? ''));
            continue;
        }
        const pair = /^([\w-]+):\s*(.*)$/.exec(line);
        if (pair) {
            const key = pair[1] ?? '';
            let value = (pair[2] ?? '').trim();
            if (value === '>' || value === '|' || value === '>-' || value === '|-') value = '';
            const inline = /^\[(.*)\]$/.exec(value);
            if (inline) {
                lists[key] = (inline[1] ?? '').split(',').map(unquote).filter(Boolean);
                value = lists[key]!.join(', ');
            } else {
                value = unquote(value);
            }
            current = { key, value };
            front.push(current);
            continue;
        }
        if (current && /^\s+\S/.test(line)) current.value = `${current.value} ${line.trim()}`.trim();
    }
    return { front, lists, body: lines.slice(end + 1).join('\n').replace(/^\n+/, '') };
}

function quoted(text: string): string[] {
    const out: string[] = [];
    for (const match of text.matchAll(/["“]([^"”\n]{3,80})["”]/g)) out.push((match[1] ?? '').trim());
    return out;
}

function sectionTriggers(body: string): string[] {
    const out: string[] = [];
    let inside = false;
    for (const line of body.split('\n')) {
        const heading = /^#{1,6}\s+(.*)$/.exec(line);
        if (heading) {
            inside = /^(triggers?|trigger phrases|you say)\b/i.test((heading[1] ?? '').trim());
            continue;
        }
        const item = /^\s*[-*]\s+(.*)$/.exec(line);
        if (inside && item) out.push(unquote((item[1] ?? '').replace(/`/g, '')));
    }
    return out;
}

export function triggersOf(text: string, description = ''): string[] {
    const split = splitSkillMd(text);
    const fromFront = [...(split.lists['triggers'] ?? []), ...(split.lists['trigger_phrases'] ?? [])];
    const descr = split.front.find((entry) => entry.key === 'description')?.value ?? description;
    const all = [...fromFront, ...quoted(descr), ...sectionTriggers(split.body)];
    const seen = new Set<string>();
    const out: string[] = [];
    for (const raw of all) {
        const phrase = raw.replace(/\s+/g, ' ').trim();
        if (phrase.length < 3 || phrase.length > 80 || seen.has(phrase.toLowerCase())) continue;
        seen.add(phrase.toLowerCase());
        out.push(phrase);
        if (out.length === MAX_TRIGGERS) break;
    }
    return out;
}

export function estimateTokens(name: string, text: string | number): number {
    return Math.ceil((name.length + (typeof text === 'number' ? text : text.length) + 8) / 4);
}

export function deciderOf(group: SkillGroupRow, harness: 'claude' | 'codex'): SkillLocationRow | undefined {
    const mine = group.locations.filter((l) => l.harness === harness);
    return mine.find((l) => l.shadowed_by === null) ?? mine[0];
}

export function canSwitchHarness(group: SkillGroupRow, harness: 'claude' | 'codex', context: ContextChoice): boolean {
    return group.locations.some((l) => l.harness === harness && switchable(l, context));
}

export type StateShapeName = 'on' | 'name-only' | 'user-invocable-only' | 'off';

export function shapeOf(state: string): StateShapeName {
    return state === 'on' || state === 'name-only' || state === 'user-invocable-only' ? state : 'off';
}

export function removeBlock(loc: SkillLocationRow): 'read_only' | 'catalog' | null {
    if (loc.read_only) return 'read_only';
    return loc.managed?.source === 'ledger' ? 'catalog' : null;
}

export function linesOf(text: string): string[] {
    return text.replace(/\r\n?/g, '\n').replace(/\n$/, '').split('\n');
}

export function agoWords(seconds: number, t: (key: string, params?: Record<string, unknown> | null) => string): string {
    const s = Math.max(0, seconds);
    if (s < 45) return t('skp.ago.now');
    const minutes = Math.max(1, Math.floor(s / 60));
    if (minutes < 60) return minutes === 1 ? t('skp.ago.minute') : t('skp.ago.minutes', { count: minutes });
    const hours = Math.floor(s / 3600);
    if (hours < 24) return hours === 1 ? t('skp.ago.hour') : t('skp.ago.hours', { count: hours });
    const days = Math.floor(s / 86400);
    if (days === 1) return t('skp.ago.yesterday');
    return days < 30 ? t('skp.ago.days', { count: days }) : '';
}
