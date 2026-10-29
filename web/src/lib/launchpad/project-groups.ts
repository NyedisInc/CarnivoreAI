/* could not */
import { instanceKey } from '../sessions/attribution';
import type { RunningSessionRow, SessionRecord } from '../sessions/types';

/* could not be read */
export const ATTENTION_REASON = {
    /* did not answer */
    listingUnreadable: 'project.attention.listing_unreadable',
    ambiguousName: 'project.attention.ambiguous_name',
    noRecord: 'project.attention.no_record',
    dirUnreadable: 'project.attention.dir_unreadable',
    noProjectId: 'project.attention.no_project_id',
    endedDirUnreadable: 'project.attention.ended_dir_unreadable',
    endedNoProjectId: 'project.attention.ended_no_project_id',
} as const;

export type AttentionReason =
    (typeof ATTENTION_REASON)[keyof typeof ATTENTION_REASON];

export interface TreeSessionRow extends RunningSessionRow {
    ended?: boolean;
    session_uuid?: string | null;
    working_dir?: string | null;
    title?: string | null;
    project_id?: number | null;
    project_attribution?: string | null;
}

/* could not */
export interface AttentionItem {
    session: TreeSessionRow;
    reasonKey: AttentionReason;
    detail?: string | null;
}

export interface ProjectSessionGroups {
    byProjectId: Map<number, TreeSessionRow[]>;
    noProject: TreeSessionRow[];
    /* could not */
    needsAttention: AttentionItem[];
}

export interface JoinInput {
    runningSessions: RunningSessionRow[];
    sessionRecords: SessionRecord[];
    sessionAttribution: Map<string, SessionRecord>;
    sessionAttributionByInstance: Map<string, SessionRecord>;
    /* could not */
    sessionAttributionAmbiguous: Set<string>;
    sessionAttributionListingOk: boolean;
    sessionAttributionListingDetail: string | null;
}

/* CANNOT DETERMINE did not answer */
export function endedSessionsForTree(input: JoinInput): TreeSessionRow[] {
    if (!input.sessionAttributionListingOk) return [];
    const liveNames = new Set(
        (input.runningSessions || []).map((s) => s.name),
    );
    const records = input.sessionRecords || [];
    const replacedByRunning = new Set<string>();
    for (const rec of records) {
        if (!rec || rec.lifecycle !== 'running') continue;
        const parent = rec.parent_session_id;
        if (parent !== null && parent !== undefined && parent !== '') {
            replacedByRunning.add(String(parent));
        }
    }
    const out: TreeSessionRow[] = [];
    for (const rec of records) {
        if (!rec || rec.archived_at) continue;
        if (rec.lifecycle !== 'stopped' && rec.lifecycle !== 'dead') continue;
        if (rec.tmux_name && liveNames.has(rec.tmux_name)) continue;
        if (rec.id !== null && rec.id !== undefined
            && replacedByRunning.has(String(rec.id))) continue;
        out.push({
            name: rec.tmux_name || '',
            label: rec.title || null,
            title: rec.title || null,
            session_uuid: rec.session_uuid,
            ended: true,
            status: 'stopped',
            is_active: false,
            created_by_cloude: !!rec.owned,
            created_at_epoch: rec.tmux_created_epoch || 0,
            working_dir: rec.working_dir || '',
            agent_type: rec.agent_type || '',
            agent_family: rec.agent_family || null,
            agent_family_source: rec.agent_family_source || null,
            project_id: rec.project_id,
            project_attribution: rec.project_attribution,
            session_row_id: (rec.id === undefined ? null : rec.id),
        });
    }
    return out;
}

/* the project row */
function pushChild(
    byProjectId: Map<number, TreeSessionRow[]>,
    id: number,
    session: TreeSessionRow,
): void {
    const list = byProjectId.get(id) || [];
    list.push(session);
    byProjectId.set(id, list);
}

export function buildProjectSessionGroups(input: JoinInput): ProjectSessionGroups {
    const byProjectId = new Map<number, TreeSessionRow[]>();
    const noProject: TreeSessionRow[] = [];
    const needsAttention: AttentionItem[] = [];
    const sessions = input.runningSessions || [];

    for (const s of sessions) {
        if (!input.sessionAttributionListingOk) {
            needsAttention.push({
                session: s,
                reasonKey: ATTENTION_REASON.listingUnreadable,
                detail: input.sessionAttributionListingDetail || null,
            });
            continue;
        }

        let rec: SessionRecord | null = null;
        if (s.created_at_epoch) {
            const key = instanceKey(s.name, s.created_at_epoch);
            if (input.sessionAttributionByInstance.has(key)) {
                rec = input.sessionAttributionByInstance.get(key) || null;
            }
        }

        if (!rec) {
            if (input.sessionAttributionAmbiguous.has(s.name)) {
                needsAttention.push({
                    session: s,
                    reasonKey: ATTENTION_REASON.ambiguousName,
                });
                continue;
            }
            rec = input.sessionAttribution.get(s.name) || null;
        }

        if (!rec) {
            needsAttention.push({
                session: s,
                reasonKey: ATTENTION_REASON.noRecord,
            });
            continue;
        }

        if (rec.archived_at) continue;

        const attribution = rec.project_attribution;
        if (attribution === 'unknown') {
            needsAttention.push({
                session: s,
                reasonKey: ATTENTION_REASON.dirUnreadable,
            });
        } else if (attribution === 'none') {
            noProject.push(s);
        } else if (rec.project_id !== null && rec.project_id !== undefined) {
            pushChild(byProjectId, rec.project_id, s);
        } else {
            needsAttention.push({
                session: s,
                reasonKey: ATTENTION_REASON.noProjectId,
            });
        }
    }

    for (const s of endedSessionsForTree(input)) {
        if (s.project_attribution === 'unknown') {
            needsAttention.push({
                session: s,
                reasonKey: ATTENTION_REASON.endedDirUnreadable,
            });
        } else if (s.project_attribution === 'none') {
            noProject.push(s);
        } else if (s.project_id !== null && s.project_id !== undefined) {
            pushChild(byProjectId, s.project_id, s);
        } else {
            needsAttention.push({
                session: s,
                reasonKey: ATTENTION_REASON.endedNoProjectId,
            });
        }
    }

    return { byProjectId, noProject, needsAttention };
}

export function rowKey(row: TreeSessionRow): string {
    return (row.ended ? 'e:' : 'l:') + row.name + ':' + (row.created_at_epoch || 0);
}
