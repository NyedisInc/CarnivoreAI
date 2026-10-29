import type { PublishableSkill } from '../catalog/publish';
import type { PublishTab } from '../catalog/menu/route';
import { kindWord, realKind, tabOf, type KindTab } from './kinds';
import { bucketOf, BUCKETS, rowWord, stageOf, type Bucket, type FolderPhase, type StageKey } from './stages';
import type { SubRow } from './types';

export const KIND_TABS: readonly KindTab[] = ['skills', 'themes', 'mods', 'plugins'];

export const KIND_OF_TAB: Record<KindTab, string> = { skills: 'skill', themes: 'theme', mods: 'mod', plugins: 'plugin' };

export function markKind(kind: string): string {
    return KIND_OF_TAB[tabOf(kind) ?? 'skills'];
}

export interface JoinInput {
    mine: readonly SubRow[] | null;
    folders: readonly PublishableSkill[] | null;
    sendsOf(location: string): readonly string[];
    checkOf(location: string): { ok: boolean; at: string } | null;
}

export interface ItemRecord {
    location: string;
    folder: PublishableSkill | null;
    kind: string;
    tab: KindTab | null;
    name: string;
    harness: string;
    subs: SubRow[];
    latest: SubRow | null;
    phase: FolderPhase;
    waits: boolean;
}

export interface RowData {
    key: string;
    location: string;
    subId: string | null;
    kind: string;
    name: string;
    version: string;
    harness: string;
    stage: StageKey | null;
    wordKey: string;
    date: string | null;
    wait: boolean;
}

function ms(stamp: string): number {
    const value = Date.parse(stamp);
    return Number.isNaN(value) ? 0 : value;
}

function phaseOf(check: { ok: boolean; at: string } | null, latest: SubRow | null, newestSent = 0): FolderPhase {
    if (!check) return 'none';
    const cutoff = Math.max(newestSent, latest ? ms(latest.created_at) : 0);
    if (cutoff > 0 && ms(check.at) > 0 && ms(check.at) <= cutoff) return 'none';
    return check.ok ? 'checked' : 'refused';
}

function waitsOn(latest: SubRow | null, phase: FolderPhase): boolean {
    return phase === 'refused' || (latest !== null && bucketOf(latest) === 'needs_you');
}

export function buildRecords(input: JoinInput): ItemRecord[] {
    const folders = input.folders ?? [];
    const sorted = (input.mine ?? []).filter((row) => !row.media_only).sort((a, b) => ms(a.created_at) - ms(b.created_at));
    const newestSent = new Map<string, number>();
    const owned = new Map<string, SubRow[]>();
    const orphans = new Map<string, SubRow[]>();
    for (const row of sorted) {
        const sent = folders.find((f) => input.sendsOf(f.location).includes(row.id));
        const same = folders.filter((f) => realKind(f) === realKind(row) && f.name === row.name);
        const home = sent ?? (same.length === 1 ? same[0] : undefined);
        if (home) newestSent.set(home.location, Math.max(newestSent.get(home.location) ?? 0, ms(row.created_at)));
        if (stageOf(row) === null) continue;
        const bucket = home ? owned.get(home.location) ?? [] : orphans.get(row.item_id) ?? [];
        bucket.push(row);
        if (home) owned.set(home.location, bucket);
        else orphans.set(row.item_id, bucket);
    }
    const out: ItemRecord[] = folders.map((f) => {
        const subs = owned.get(f.location) ?? [];
        const latest = subs.at(-1) ?? null;
        const phase = phaseOf(input.checkOf(f.location), latest, newestSent.get(f.location) ?? 0);
        return { location: f.location, folder: f, kind: realKind(f), tab: tabOf(f.kind), name: f.name, harness: f.harness ?? '', subs, latest, phase, waits: waitsOn(latest, phase) };
    });
    for (const [itemId, subs] of orphans) {
        const latest = subs.at(-1) ?? null;
        const first = subs[0] as SubRow;
        out.push({ location: `item:${itemId}`, folder: null, kind: realKind(first), tab: tabOf(first.kind), name: first.name, harness: '', subs, latest, phase: 'none', waits: waitsOn(latest, 'none') });
    }
    return out;
}

function rowOf(record: ItemRecord, onSubmissions: boolean): RowData {
    const latest = record.latest;
    return {
        key: onSubmissions && latest ? latest.id : record.location,
        location: record.location,
        subId: onSubmissions && latest ? latest.id : null,
        kind: record.kind,
        name: record.name,
        version: onSubmissions && latest ? latest.version : '',
        harness: record.harness,
        stage: latest ? stageOf(latest) : null,
        wordKey: rowWord(latest, onSubmissions ? 'none' : record.phase),
        date: onSubmissions && latest ? latest.created_at : null,
        wait: onSubmissions ? waitsOn(latest, record.phase) : record.waits,
    };
}

function matches(parts: readonly string[], query: string): boolean {
    const q = query.trim().toLowerCase();
    return q === '' || parts.join(' ').toLowerCase().includes(q);
}

function bucketOfRecord(record: ItemRecord): Bucket {
    return record.phase === 'refused' ? 'needs_you' : bucketOf(record.latest as SubRow);
}

export function submissionGroups(records: readonly ItemRecord[], query: string, t: (key: string) => string): { bucket: Bucket; rows: RowData[] }[] {
    const shown = records.filter((r) => r.latest !== null);
    const hits = shown.filter((r) => matches([r.name, (r.latest as SubRow).version, t(rowWord(r.latest, 'none')), t(kindWord(r.kind)), r.harness], query));
    return BUCKETS.map((bucket) => ({
        bucket,
        rows: hits
            .filter((r) => bucketOfRecord(r) === bucket)
            .sort((a, b) => ms((b.latest as SubRow).created_at) - ms((a.latest as SubRow).created_at))
            .map((r) => rowOf(r, true)),
    })).filter((g) => g.rows.length > 0);
}

export function kindList(records: readonly ItemRecord[], tab: KindTab, query: string): RowData[] {
    return records
        .filter((r) => r.folder !== null && r.tab === tab && matches([r.name, r.harness], query))
        .sort((a, b) => Number(b.waits) - Number(a.waits) || a.name.localeCompare(b.name) || a.harness.localeCompare(b.harness))
        .map((r) => rowOf(r, false));
}

export interface TabStat {
    count: number | null;
    waits: boolean;
}

export function tabStats(records: readonly ItemRecord[], failed: { submissions: boolean; kinds: boolean } = { submissions: false, kinds: false }): Record<PublishTab, TabStat> {
    const stats = {} as Record<PublishTab, TabStat>;
    const subs = records.filter((r) => r.latest !== null);
    stats.submissions = { count: failed.submissions && subs.length === 0 ? null : subs.length, waits: subs.some((r) => waitsOn(r.latest, r.phase)) };
    for (const tab of KIND_TABS) {
        const inTab = records.filter((r) => r.folder !== null && r.tab === tab);
        stats[tab] = { count: failed.kinds && inTab.length === 0 ? null : inTab.length, waits: inTab.some((r) => r.waits) };
    }
    return stats;
}

export function effectiveSub(record: ItemRecord, selSub: string | null): string | null {
    return selSub && record.subs.some((s) => s.id === selSub) ? selSub : record.latest?.id ?? null;
}

export type StepKind = 'gates' | 'check' | 'image' | 'stage';

export function stepKindOf(key: string): StepKind {
    if (key.endsWith(':gates')) return 'gates';
    if (key.endsWith(':chk') || /^chk\d+:/.test(key)) return 'check';
    if (key.endsWith(':img')) return 'image';
    return 'stage';
}
