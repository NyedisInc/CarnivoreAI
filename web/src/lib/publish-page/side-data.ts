import type { PageStore } from './page-store.svelte';
import { cardOf, type CardInput, type CardView } from './card-model';
import { hasTwin, itemFacts, kindLine, markOf, rowsOfItem, stepFor } from './item-model';
import type { ItemRecord } from './list-model';
import type { Translate } from '../sessions/types';
import { buildTimeline, type CheckLike, type SendLike, type TimelineInput, type TlItem } from './timeline-model';
import type { SubRow } from './types';
import { draftsOf } from './wizard-state.svelte';

function sendsOf(store: PageStore, rec: ItemRecord): (SendLike & { hero_sha: string })[] {
    return (store.facts[rec.location]?.sends ?? [])
        .map((s) => ({ submission_id: s.submission_id, version: s.version, sent_at: s.sent_at, hero: s.hero, media_submission_id: s.media_submission_id ?? '', hero_sha: s.hero_sha ?? '' }))
        .sort((a, b) => (Date.parse(b.sent_at) || 0) - (Date.parse(a.sent_at) || 0));
}

function mediaOf(store: PageStore, rec: ItemRecord, rows: readonly SubRow[]): SubRow[] {
    const items = new Set([...rows, ...rec.subs].map((r) => r.item_id));
    const twin = hasTwin(rec, store.folders);
    return (store.mine ?? []).filter((r) => r.media_only && (items.has(r.item_id) || (!twin && rec.folder !== null && r.kind === rec.kind && r.name === rec.name)));
}

function checksOf(store: PageStore, rec: ItemRecord): CheckLike[] {
    const stored = store.facts[rec.location]?.checks ?? [];
    const visit = store.checks[rec.location];
    const list: CheckLike[] = stored.length ? stored.map((c) => ({ ...c, preview: c.files == null ? undefined : { notes: 0, files: c.files, bytes: c.bytes ?? 0, grade: c.grade ?? '' } })) : visit ? [{ version: visit.version, ok: visit.ok, at: visit.at, summary: visit.summary }] : [];
    const pv = visit?.preview;
    if (pv && list[0] && list[0].version === visit.version) {
        list[0].preview = { notes: pv.lint?.failed?.length ?? 0, files: pv.file_count, bytes: pv.total_bytes, grade: pv.lint?.grade ?? '' };
    }
    return list;
}

export function timelineInputOf(store: PageStore, rec: ItemRecord): TimelineInput {
    const facts = store.facts[rec.location];
    const sends = sendsOf(store, rec);
    const rows = rowsOfItem(rec, store.mine, sends.map((s) => s.submission_id), hasTwin(rec, store.folders));
    return {
        name: rec.name,
        kind: rec.kind,
        folderKey: kindLine(rec).folder,
        rows,
        media: mediaOf(store, rec, rows),
        sends,
        checks: checksOf(store, rec),
        madeAt: facts?.made_at ?? '',
        fileCount: itemFacts(facts)?.file_count ?? 0,
        reports: store.reports,
        heroOutcome: draftsOf(store).of(rec.location).heroOutcome,
    };
}

export function timelineOf(store: PageStore, rec: ItemRecord, t: Translate, folded = true): TlItem[] {
    return buildTimeline(timelineInputOf(store, rec), t, folded);
}

export function cardViewOf(store: PageStore, rec: ItemRecord, t: Translate): CardView & { replaceable: boolean; kind: string } {
    const draft = draftsOf(store).of(rec.location);
    const drafting = stepFor(store, rec).kind === 'send';
    const sends = sendsOf(store, rec);
    const rows = rowsOfItem(rec, store.mine, sends.map((x) => x.submission_id), hasTwin(rec, store.folders));
    const input: CardInput = {
        drafting,
        draft: { url: draft.hero.url, own: draft.hero.mode === 'own' },
        outcome: draft.heroOutcome,
        send: sends[0] ? { hero: sends[0].hero, sha: sends[0].hero_sha } : null,
        media: mediaOf(store, rec, rows),
        kind: markOf(rec),
    };
    return { ...cardOf(input, t), replaceable: (rows.length > 0 || sends.length > 0 || rec.latest !== null) && !drafting, kind: input.kind };
}
