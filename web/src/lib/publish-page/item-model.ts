import type { PublishableSkill } from '../catalog/publish';
import type { Translate } from '../sessions/types';
import type { ItemFacts } from './api-facts';
import { dateText } from './format';
import { buildRecords, markKind, type ItemRecord } from './list-model';
import { foundByFact, folderPhrase, kindWord, tabOf } from './kinds';
import { stepOf, type Step } from './next-step-model';
import type { PageStore } from './page-store.svelte';
import type { Facts, SubRow } from './types';

const HOUR = 3_600_000;

export function selectedRecord(store: PageStore): ItemRecord | null {
    if (!store.sel) return null;
    const records = buildRecords({
        mine: store.mine,
        folders: store.folders,
        sendsOf: (location) => store.facts[location]?.sends.map((s) => s.submission_id) ?? [],
        checkOf: (location) => {
            const check = store.checkOf(location);
            return check ? { ok: check.ok, at: check.at } : null;
        },
    });
    return records.find((r) => r.location === store.sel) ?? null;
}

export function itemFacts(facts: Facts | undefined): ItemFacts | null {
    return facts && 'files' in facts ? (facts as ItemFacts) : null;
}

export function vcmp(a: string, b: string): number {
    const pa = a.split('.').map((n) => Number.parseInt(n, 10) || 0);
    const pb = b.split('.').map((n) => Number.parseInt(n, 10) || 0);
    for (let i = 0; i < 3; i++) {
        const gap = (pa[i] ?? 0) - (pb[i] ?? 0);
        if (gap !== 0) return gap;
    }
    return 0;
}

export function bump(version: string): string {
    const parts = version.split('.').map((n) => Number.parseInt(n, 10) || 0);
    return `${parts[0] ?? 0}.${parts[1] ?? 0}.${(parts[2] ?? 0) + 1}`;
}

export function maxVersion(versions: readonly string[]): string {
    return versions.reduce((best, v) => (best === '' || vcmp(v, best) > 0 ? v : best), '');
}

export function defaultVersion(declared: string, sent: string): string {
    const local = declared || sent || '1.0.0';
    return sent && vcmp(local, sent) <= 0 ? bump(sent) : local;
}

export function versionRows(rec: ItemRecord, mine: readonly SubRow[] | null): SubRow[] {
    const items = new Set(rec.subs.map((s) => s.item_id));
    return (mine ?? [])
        .filter((row) => items.has(row.item_id) && !row.media_only && row.status !== 'withdrawn')
        .sort((a, b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0));
}

export function sentRows(store: PageStore, rec: ItemRecord): SubRow[] {
    const sends = store.facts[rec.location]?.sends.map((s) => s.submission_id) ?? [];
    return rowsOfItem(rec, store.mine, sends, hasTwin(rec, store.folders)).reverse();
}

export interface ThreeVersions {
    approved: string;
    sent: string;
    onComputer: string;
}

export function threeVersions(rows: readonly SubRow[], declared: string): ThreeVersions {
    const live = rows.filter((row) => row.status === 'published');
    return { approved: maxVersion(live.map((r) => r.version)), sent: maxVersion(rows.map((r) => r.version)), onComputer: declared };
}

export interface ChangedNote {
    version: string;
    count: number;
    hours: number;
}

/* nothing was sent */
export function changedNote(rec: ItemRecord, facts: Facts | undefined, now: number): ChangedNote | null {
    if (!rec.latest || !facts || facts.changed_files <= 0) return null;
    const at = Date.parse(facts.changed_at);
    const hours = Number.isNaN(at) ? 0 : Math.max(0, Math.round(((now - at) / HOUR) * 10) / 10);
    return { version: rec.latest.version, count: facts.changed_files, hours };
}

export interface FactLine {
    label: string;
    value: string;
}

export function grouped(n: number): string {
    return String(Math.max(0, Math.trunc(n))).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

export function factLines(rec: ItemRecord, facts: Facts | undefined, t: Translate): FactLine[] {
    const lines: FactLine[] = [{ label: t('publish.page.fact.kind'), value: t(kindWord(rec.kind)) }];
    const found = foundByFact({ kind: rec.kind });
    if (found) lines.push({ label: t(found.label), value: t(found.value) });
    lines.push({ label: t('publish.page.fact.works_with'), value: rec.harness || t('publish.page.fact.any_session') });
    const tab = tabOf(rec.kind);
    if (tab && rec.folder) lines.push({ label: t('publish.page.fact.read_from'), value: t(folderPhrase(tab)) });
    const full = itemFacts(facts);
    if (!full) return lines;
    lines.push({ label: t('publish.page.fact.files'), value: t('publish.page.fact.files_value', { count: full.file_count, bytes: grouped(full.total_bytes) }) });
    lines.push({ label: t('publish.page.fact.license'), value: full.license || (full.license_file ? 'LICENSE' : t('publish.page.fact.license_none')) });
    const grade = full.grade.toLowerCase();
    lines.push({
        label: t('publish.page.fact.grade'),
        value: grade === 'a' || grade === 'b' || grade === 'c' ? t('publish.page.fact.grade_value', { grade: full.grade, note: t(`publish.page.grade.${grade}`) }) : t('publish.page.fact.grade_none'),
    });
    if (full.description_tokens_est > 0) lines.push({ label: t('publish.page.fact.listing_cost'), value: t('publish.page.fact.cost_value', { tokens: full.description_tokens_est }) });
    const made = dateText(full.made_at, t);
    if (made) lines.push({ label: t('publish.page.fact.made_here'), value: made });
    return lines;
}

export function kindLine(rec: ItemRecord): { kind: string; folder: string | null } {
    const tab = tabOf(rec.kind);
    return { kind: kindWord(rec.kind), folder: tab && rec.folder ? folderPhrase(tab) : null };
}

export function markOf(rec: ItemRecord): string {
    return markKind(rec.kind);
}

export function hasChecks(row: SubRow): boolean {
    return !(row.status === 'pending' && row.gate_state === 'received');
}

export function rowsOfItem(rec: ItemRecord, mine: readonly SubRow[] | null, sendIds: readonly string[], twins: boolean): SubRow[] {
    const items = new Set(rec.subs.map((s) => s.item_id));
    const sent = new Set(sendIds);
    return (mine ?? [])
        .filter((row) => !row.media_only)
        .filter((row) => sent.has(row.id) || items.has(row.item_id) || (!twins && rec.folder !== null && row.kind === rec.kind && row.name === rec.name))
        .sort((a, b) => (Date.parse(a.created_at) || 0) - (Date.parse(b.created_at) || 0));
}

export function hasTwin(rec: ItemRecord, folders: readonly PublishableSkill[] | null): boolean {
    return (folders ?? []).filter((f) => f.name === rec.name && (f.kind ?? 'skill') === rec.kind && f.location !== rec.location).length > 0;
}

export function withdrawnAfter(rec: ItemRecord, mine: readonly SubRow[] | null, sendIds: readonly string[], twins: boolean): SubRow | null {
    const when = (row: SubRow): number => Date.parse(row.created_at) || 0;
    const newest = rowsOfItem(rec, mine, sendIds, twins)
        .filter((row) => row.status === 'withdrawn')
        .sort((a, b) => when(b) - when(a))[0];
    if (!newest) return null;
    return rec.latest && when(rec.latest) > when(newest) ? null : newest;
}

export function factsUnknown(store: PageStore, rec: ItemRecord): boolean {
    return !!store.failure.facts && rec.folder !== null && !store.facts[rec.location];
}

/* could not be read */
export function onComputerValue(input: { folderListFailed: boolean; hasFolder: boolean; declared: string; none: string }): string {
    if (input.folderListFailed && !input.hasFolder) return '-';
    return input.declared || input.none;
}

export function stepFor(store: PageStore, rec: ItemRecord): Step {
    const facts = store.facts[rec.location];
    const forced = rec.location in store.forced && store.forced[rec.location] === (rec.latest?.id ?? '');
    return stepOf({
        latest: rec.latest,
        withdrawn: withdrawnAfter(rec, store.mine, facts?.sends.map((s) => s.submission_id) ?? [], hasTwin(rec, store.folders)),
        phase: rec.phase,
        force: forced,
    });
}
