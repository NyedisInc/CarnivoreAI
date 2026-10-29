import type { SubmissionReport } from '../catalog/publish';
import type { Translate } from '../sessions/types';
import { mentionSkipped } from './checks-model';
import { clockText, dateText } from './format';
import { grouped } from './item-model';
import { failedCount, resultsOf, type CheckResult } from './report-format';
import { stageKey, type StageKey } from './stages';
import type { SubRow } from './types';
import type { HeroOutcome } from './wizard-model';

export const FOLD_AFTER = 16;
const KEEP_OPEN = 2;

export type Mark = { kind: 'stage'; stage: StageKey } | { kind: 'verdict'; result: CheckResult } | { kind: 'icon'; name: string };

export interface StageDetail {
    stage: 'approved' | 'rejected';
    pulled: boolean;
    reason: string;
    left: number | null;
    subId: string;
}

export interface TlEntry {
    kind: 'entry';
    key: string;
    ts: number;
    grp: string;
    title: string;
    meta: string;
    mark: Mark;
    open: boolean;
    detail?: StageDetail;
}

export interface TlFold {
    kind: 'fold';
    key: string;
    ts: number;
    summary: string;
    lines: { title: string; ts: number }[];
}

export type TlItem = TlEntry | TlFold;

export interface SendLike {
    submission_id: string;
    version: string;
    sent_at: string;
    hero: string;
    media_submission_id: string;
}

export interface CheckLike {
    version: string;
    ok: boolean;
    at: string;
    summary: string;
    preview?: { notes: number; files: number; bytes: number; grade: string } | null;
}

export interface TimelineInput {
    name: string;
    kind: string;
    folderKey: string | null;
    rows: readonly SubRow[];
    media: readonly SubRow[];
    sends: readonly SendLike[];
    checks: readonly CheckLike[];
    madeAt: string;
    fileCount: number;
    reports: Record<string, SubmissionReport>;
    heroOutcome: HeroOutcome;
}

function ms(stamp: string): number {
    const value = Date.parse(stamp);
    return Number.isNaN(value) ? 0 : value;
}

const opens = (type: string): boolean => type === 'gates' || type === 'check' || type === 'image' || type === 'approved' || type === 'rejected';

type Raw = TlEntry & { seq: number };

export function buildTimeline(input: TimelineInput, t: Translate, folded = true): TlItem[] {
    const out: Raw[] = [];
    const push = (e: Omit<TlEntry, 'kind'>): void => {
        if (e.ts > 0) out.push({ ...e, kind: 'entry', seq: out.length });
    };
    const sendOf = new Map(input.sends.map((s) => [s.submission_id, s]));
    const mediaSend = new Map(input.sends.filter((s) => s.media_submission_id).map((s) => [s.media_submission_id, s]));
    const newestSend = input.sends[0];

    push({ key: 'made', ts: ms(input.madeAt), grp: 'head', title: t('publish.page.timeline.made.title'), meta: input.folderKey && input.fileCount > 0 ? t('publish.page.timeline.made.meta', { count: input.fileCount, folder: t(input.folderKey) }) : '', mark: { kind: 'icon', name: 'folder' }, open: false });

    const taken = new Set<string>();
    input.checks.forEach((c, i) => {
        const at = ms(c.at);
        const owner = input.rows.find((r) => r.version === c.version && sendOf.has(r.id) && ms(sendOf.get(r.id)?.sent_at ?? '') >= at && !taken.has(r.id));
        if (owner && c.ok) taken.add(owner.id);
        const notes = c.preview?.notes ?? 0;
        const title = c.ok
            ? notes > 0 ? t('publish.page.timeline.check_notes.title', { version: c.version, count: notes }) : t('publish.page.timeline.check_clean.title', { version: c.version })
            : t('publish.page.timeline.check_failed.title', { version: c.version, codes: c.summary });
        const p = c.preview;
        const meta = c.ok && p ? t(p.grade ? 'publish.page.timeline.check.meta_graded' : 'publish.page.timeline.check.meta', { grade: p.grade, count: p.files, bytes: grouped(p.bytes) }) : '';
        push({ key: `chk${i}:${at}`, ts: at, grp: owner ? owner.id : 'tail', title, meta, mark: { kind: 'verdict', result: !c.ok ? 'did_not_pass' : notes > 0 ? 'note' : 'passed' }, open: true });
    });

    for (const row of input.rows) {
        const grp = row.id;
        const report = input.reports[row.id] ?? null;
        const send = sendOf.get(row.id);
        const stamps: SubRow['events'] = row.events.length ? row.events : stampEvents(row);
        const lastWhat = stamps.at(-1)?.what ?? '';
        let gated = false;
        let appealed = false;
        const decisions = stamps.filter((e) => e.what === 'rejected');
        const published = stamps.some((e) => e.what === 'published') || row.status === 'published';
        const entry = (key: string, e: Omit<TlEntry, 'kind' | 'key' | 'grp'>): void => push({ key: `${grp}:${key}`, grp, ...e });

        let sentTs = 0;
        if (send) {
            const hero = send.hero === 'yours' ? t('publish.page.timeline.sent.meta_yours') : send.hero === 'made' ? t('publish.page.timeline.sent.meta_made') : '';
            const sentAt = Math.min(ms(send.sent_at) || Infinity, ms(row.created_at) || Infinity);
            sentTs = Number.isFinite(sentAt) ? sentAt : 0;
            entry('sent', { ts: sentTs, title: t('publish.page.timeline.sent.title', { version: row.version }), meta: hero, mark: { kind: 'icon', name: 'upload' }, open: false });
        }
        if (send && input.heroOutcome === 'making' && send === newestSend) {
            entry('img', { ts: sentTs, title: t('publish.page.timeline.image_generating.title'), meta: t('publish.page.timeline.image_generating.meta'), mark: { kind: 'stage', stage: 'in_review' }, open: true });
        } else if (send && input.heroOutcome === 'failed' && send === newestSend) {
            entry('img', { ts: sentTs, title: t('publish.new.hero_failed'), meta: '', mark: { kind: 'icon', name: 'image' }, open: true });
        }

        for (const e of stamps) {
            const ts = ms(e.at);
            switch (e.what) {
                case 'received':
                    entry('recv', { ts, title: t('publish.page.timeline.received.title'), meta: '', mark: { kind: 'stage', stage: 'submitted' }, open: false });
                    break;
                case 'gating':
                    if (row.status === 'pending' && row.gate_state === 'gating') entry('gates', { ts, title: t('publish.page.timeline.gating.title'), meta: '', mark: { kind: 'stage', stage: 'in_review' }, open: opens('gates') });
                    break;
                case 'gate_failed': {
                    gated = true;
                    const count = report ? failedCount(resultsOf(report.gates)) : null;
                    entry('gates', {
                        ts,
                        title: count === null ? t(stageKey('rejected')) : t('publish.page.timeline.gate_failed.title', { count }),
                        meta: t('publish.page.timeline.gate_failed.meta'),
                        mark: { kind: 'stage', stage: 'rejected' },
                        open: true,
                    });
                    break;
                }
                case 'awaiting_approval': {
                    if (!gated) {
                        gated = true;
                        const skipped = mentionSkipped(report, row.kind) ? t('publish.page.timeline.gate_passed.skipped_suffix') : '';
                        entry('gates', { ts, title: t('publish.page.timeline.gate_passed.title'), meta: t('publish.page.timeline.gate_passed.meta') + skipped, mark: { kind: 'verdict', result: 'passed' }, open: true });
                    }
                    entry(appealed ? 'wait2' : 'wait', {
                        ts,
                        title: t(appealed ? 'publish.page.timeline.awaiting_approval.again_title' : 'publish.page.timeline.awaiting_approval.title'),
                        meta: t(row.status === 'publishing' ? 'publish.page.timeline.publishing.meta' : appealed ? 'publish.page.timeline.awaiting_approval.again_meta' : 'publish.page.timeline.awaiting_approval.meta'),
                        mark: { kind: 'stage', stage: 'in_review' },
                        open: false,
                    });
                    break;
                }
                case 'approved':
                    if (row.status === 'publishing') break;
                    entry('appr', {
                        ts,
                        title: t('publish.page.timeline.approved.title'),
                        meta: published ? t('publish.page.timeline.published.meta', { name: row.item_id || row.name, version: row.version }) : t('publish.page.timeline.approved.meta'),
                        mark: { kind: 'stage', stage: 'approved' },
                        open: true,
                        detail: { stage: 'approved', pulled: false, reason: '', left: null, subId: row.id },
                    });
                    break;
                case 'rejected': {
                    const nth = decisions.indexOf(e);
                    const later = stamps.slice(stamps.indexOf(e) + 1).some((x) => x.what === 'appealed');
                    const left = !later && row.status === 'rejected' ? row.appeals_left : null;
                    entry(nth === 0 ? 'rej' : `rej${nth}`, {
                        ts,
                        title: t('publish.page.timeline.rejected.title', { reason: e.reason ?? '' }),
                        meta: later ? t('publish.page.timeline.rejected.meta_appealed') : left === null ? '' : left > 0 ? t('publish.page.timeline.rejected.meta', { count: left }) : t('publish.page.timeline.rejected.meta_none'),
                        mark: { kind: 'stage', stage: 'rejected' },
                        open: true,
                        detail: { stage: 'rejected', pulled: false, reason: e.reason ?? '', left, subId: row.id },
                    });
                    break;
                }
                case 'appealed':
                    appealed = true;
                    entry(`ap${ts}`, { ts, title: t('publish.page.timeline.appeal.title'), meta: e.text ?? '', mark: { kind: 'icon', name: 'external' }, open: false });
                    if (lastWhat === 'appealed' && row.status === 'pending') {
                        entry('wait2', { ts: ts + 1, title: t('publish.page.timeline.awaiting_approval.again_title'), meta: t('publish.page.timeline.awaiting_approval.again_meta'), mark: { kind: 'stage', stage: 'in_review' }, open: false });
                    }
                    break;
                case 'revoked': {
                    const reason = e.reason || row.revocation_reason;
                    entry('rv', {
                        ts,
                        title: t('publish.page.timeline.revoked.title', { reason: reason || t('publish.page.timeline.revoked.default_reason') }),
                        meta: t('publish.page.timeline.revoked.meta'),
                        mark: { kind: 'stage', stage: 'rejected' },
                        open: true,
                        detail: { stage: 'rejected', pulled: true, reason, left: null, subId: row.id },
                    });
                    break;
                }
                case 'withdrawn':
                    entry('wd', { ts, title: t('publish.page.timeline.withdrawn.title', { version: row.version }), meta: t('publish.page.timeline.withdrawn.meta'), mark: { kind: 'icon', name: 'close' }, open: false });
                    break;
                case 'superseded':
                    entry('rp', {
                        ts,
                        title: e.version ? t('publish.page.timeline.superseded.title', { version: e.version }) : t('publish.page.timeline.superseded.title_unknown'),
                        meta: t('publish.page.timeline.superseded.meta'),
                        mark: { kind: 'icon', name: 'refresh' },
                        open: false,
                    });
                    break;
                default:
                    break;
            }
        }
    }

    for (const m of input.media) {
        const send = mediaSend.get(m.id);
        const title = send ? t(send.hero === 'made' ? 'publish.page.timeline.image_made.title' : 'publish.page.timeline.image_chosen.title') : t('publish.page.timeline.image_sent.title');
        push({ key: `${m.id}:img`, ts: ms(m.created_at), grp: send ? send.submission_id : 'tail', title, meta: '', mark: { kind: 'icon', name: 'image' }, open: true });
    }

    out.sort((a, b) => (a.grp === 'head' ? -1 : 0) - (b.grp === 'head' ? -1 : 0) || a.ts - b.ts || a.seq - b.seq);
    const steps = out.map(({ seq: _seq, ...entry }) => entry);
    return folded ? fold(steps, input.rows, t) : steps;
}

function stampEvents(row: SubRow): SubRow['events'] {
    const out: SubRow['events'] = [{ at: row.created_at, what: 'received' }];
    if (row.decided_at) {
        if (row.status === 'approved' || row.status === 'published' || row.status === 'publishing') out.push({ at: row.decided_at, what: 'approved' });
        else if (row.status === 'rejected') out.push({ at: row.decided_at, what: 'rejected', reason: row.reason });
        else if (row.status === 'gate_failed') out.push({ at: row.decided_at, what: 'gate_failed' });
    }
    if (row.status === 'revoked' && row.revoked_at) out.push({ at: row.revoked_at, what: 'revoked', reason: row.revocation_reason });
    return out;
}

function fold(steps: TlEntry[], rows: readonly SubRow[], t: Translate): TlItem[] {
    if (steps.length <= FOLD_AFTER || rows.length <= KEEP_OPEN) return steps;
    const keep = new Set(rows.slice(-KEEP_OPEN).map((r) => r.id));
    const versionOf = new Map(rows.map((r) => [r.id, r.version]));
    const out: TlItem[] = [];
    let bucket: { first: TlEntry; versions: string[]; lines: TlFold['lines'] } | null = null;
    const close = (): void => {
        if (!bucket) return;
        const { versions, lines, first } = bucket;
        const summary = versions.length > 1
            ? t('publish.page.timeline.fold_range', { first: versions[0], last: versions[versions.length - 1], count: lines.length })
            : t('publish.page.timeline.fold_single', { version: versions[0], count: lines.length });
        out.push({ kind: 'fold', key: `fold:${first.key}`, ts: first.ts, summary, lines });
        bucket = null;
    };
    for (const e of steps) {
        if (e.grp === 'head' || e.grp === 'tail' || keep.has(e.grp)) {
            close();
            out.push(e);
            continue;
        }
        bucket ??= { first: e, versions: [], lines: [] };
        const v = versionOf.get(e.grp);
        if (v && !bucket.versions.includes(v)) bucket.versions.push(v);
        bucket.lines.push({ title: e.title, ts: e.ts });
    }
    close();
    return out;
}

export function whenText(ts: number, t: Translate): string {
    return `${dateText(ts, t)} ${clockText(ts, t)}`;
}
