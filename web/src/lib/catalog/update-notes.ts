import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
import type { Translate } from '../sessions/types';
import type { CplugFactsData, UpdateDiff } from './types';

export type UpdateNoteTone = 'ok' | 'info' | 'warn' | 'accent';

export interface UpdateNoteItem {
    readonly icon: string;
    readonly tone: UpdateNoteTone;
    readonly text: string;
}

const MAX_NOTES = 6;
const MAX_LINE_CHARS = 180;

export function hasCplugCapabilities(facts: CplugFactsData | null | undefined): boolean {
    if (!facts) return false;
    return (
        (facts.permissions?.length ?? 0) > 0 ||
        (facts.tools?.length ?? 0) > 0 ||
        (facts.network_hosts?.length ?? 0) > 0 ||
        (facts.lan_hosts?.length ?? 0) > 0 ||
        (facts.secrets?.length ?? 0) > 0
    );
}

function cleanMarkdownLine(raw: string): string {
    let s = raw.trim();
    if (!s || s.startsWith('```') || s.startsWith('<!--') || /^[-*_]{3,}$/.test(s)) return '';
    if (/^#{1,6}\s+/.test(s)) return '';
    s = s.replace(/^(?:[-*+]|\d+[.)])\s+/, '');
    s = s.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
    s = s.replace(/[*_`]+/g, '').replace(/\s+/g, ' ').trim();
    if (s.length < 4) return '';
    if (s.length > MAX_LINE_CHARS) {
        const cut = s.slice(0, MAX_LINE_CHARS);
        const lastSpace = cut.lastIndexOf(' ');
        s = (lastSpace > MAX_LINE_CHARS * 0.6 ? cut.slice(0, lastSpace) : cut).replace(/[,;:\s]+$/, '') + '…';
    }
    return s;
}

function classifyNote(text: string): { icon: string; tone: UpdateNoteTone } {
    const low = text.toLowerCase();
    if (/\b(key|keys|arrow|rotate|shortcut|control|controls|keyboard|button|input)\b/.test(low)) {
        return { icon: 'keyboard', tone: 'info' };
    }
    if (/\b(style|theme|color|colour|icon|glyph|layout|visual|look|skin|3d|ui|modal|banner)\b/.test(low)) {
        return { icon: 'palette', tone: 'accent' };
    }
    if (/\b(screenshot|image|preview|gallery|photo)\b/.test(low)) {
        return { icon: 'image', tone: 'info' };
    }
    if (/\b(fix|fixed|bug|crash|error|issue|faster|perf|speed|improv)\b/.test(low)) {
        return { icon: 'bolt', tone: 'warn' };
    }
    if (/\b(add|added|new|feature|support|enable)\b/.test(low)) {
        return { icon: 'spark', tone: 'ok' };
    }
    return { icon: 'check-circle', tone: 'ok' };
}

function notesFromLines(lines: readonly string[]): UpdateNoteItem[] {
    const seen = new Set<string>();
    const out: UpdateNoteItem[] = [];
    for (const raw of lines) {
        const cleaned = cleanMarkdownLine(raw);
        if (!cleaned) continue;
        const key = cleaned.toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        const { icon, tone } = classifyNote(cleaned);
        out.push({ icon, tone, text: cleaned });
        if (out.length >= MAX_NOTES) break;
    }
    return out;
}

function addedDiffLines(diffText: string | null | undefined): string[] {
    if (!diffText) return [];
    const out: string[] = [];
    for (const line of diffText.split('\n')) {
        if (line.startsWith('+') && !line.startsWith('+++')) {
            out.push(line.slice(1));
        }
    }
    return out;
}

function fallbackFromChanges(diff: UpdateDiff | null | undefined, t: Translate): UpdateNoteItem[] {
    if (!diff || diff.changes.length === 0) return [];
    const flags = { ui: false, style: false, code: false, media: false, meta: false, docs: false };
    for (const ch of diff.changes) {
        const p = (ch.path || '').toLowerCase();
        if (/\.(css|scss)$/.test(p)) flags.style = true;
        else if (/\.(html|svelte|vue|jsx|tsx)$/.test(p)) flags.ui = true;
        else if (/\.(png|jpg|jpeg|webp|svg|gif|ico)$/.test(p)) flags.media = true;
        else if (/(carnivore\.toml|manifest\.json|cplug\.json|plugin\.json)$/.test(p)) flags.meta = true;
        else if (/\.(md|txt)$/.test(p)) flags.docs = true;
        else if (/\.(js|mjs|ts|py|sh)$/.test(p)) flags.code = true;
    }
    const items: UpdateNoteItem[] = [];
    if (flags.ui) items.push({ icon: 'spark', tone: 'ok', text: t(SKILL_KEYS.updateNoteUi) });
    if (flags.style) items.push({ icon: 'palette', tone: 'accent', text: t(SKILL_KEYS.updateNoteStyle) });
    if (flags.code) items.push({ icon: 'bolt', tone: 'info', text: t(SKILL_KEYS.updateNoteCode) });
    if (flags.media) items.push({ icon: 'image', tone: 'info', text: t(SKILL_KEYS.updateNoteMedia) });
    if (flags.docs) items.push({ icon: 'docs', tone: 'ok', text: t(SKILL_KEYS.updateNoteDocs) });
    if (flags.meta && items.length === 0) {
        items.push({ icon: 'settings', tone: 'info', text: t(SKILL_KEYS.updateNoteMeta) });
    }
    if (items.length === 0) {
        items.push({
            icon: 'check-circle',
            tone: 'ok',
            text: t(SKILL_KEYS.updateNoteFiles, { count: diff.changes.length }),
        });
    }
    return items.slice(0, 4);
}

export function buildUpdateNotes(args: {
    readonly releaseNotes?: string | null;
    readonly diff?: UpdateDiff | null;
    readonly fromVersion?: string | null;
    readonly toVersion?: string | null;
    readonly t: Translate;
}): readonly UpdateNoteItem[] {
    if (args.releaseNotes && args.releaseNotes.trim()) {
        const parsed = notesFromLines(args.releaseNotes.split('\n'));
        if (parsed.length > 0) return parsed;
    }

    const changes = args.diff?.changes ?? [];
    const changelogFile = changes.find((c) => /(^|\/)(changelog|release[_-]?notes)\.md$/i.test(c.path));
    if (changelogFile?.diff) {
        const parsed = notesFromLines(addedDiffLines(changelogFile.diff));
        if (parsed.length > 0) return parsed;
    }

    const readmeFile = changes.find((c) => /(^|\/)readme\.md$/i.test(c.path));
    if (readmeFile?.diff) {
        const parsed = notesFromLines(addedDiffLines(readmeFile.diff));
        if (parsed.length > 0) return parsed;
    }

    const fallback = fallbackFromChanges(args.diff, args.t);
    if (fallback.length > 0) return fallback;

    const to = args.toVersion?.trim();
    return [
        {
            icon: 'spark',
            tone: 'ok',
            text: to ? args.t(SKILL_KEYS.updateNoteVersion, { version: to }) : args.t(SKILL_KEYS.updateNoteGeneric),
        },
    ];
}
