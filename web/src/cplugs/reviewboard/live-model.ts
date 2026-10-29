import type { BoardRevision, BoardSidecar } from './board-model';

export const LIVE_ID = 'draft';

export function withLiveDraft(sidecar: BoardSidecar | null): BoardSidecar | null {
  const draft = sidecar?.live?.draft;
  if (!sidecar || !draft) return sidecar;
  const stand: BoardRevision = {
    id: LIVE_ID, n: sidecar.revisions.length + 1, created_at: draft.updated_at, summary: draft.summary, answers_round: null, viewport: draft.viewport,
    views: draft.views, prompts: draft.prompts, anchors: draft.anchors, max_width: draft.max_width ?? null, inline_picks: draft.inline_picks ?? null, stamp: String(draft.seq),
  };
  return { ...sidecar, revisions: [...sidecar.revisions, stand] };
}

export function isLiveDraft(revision: Pick<BoardRevision, 'id'> | string | null | undefined): boolean {
  return (typeof revision === 'string' ? revision : revision?.id) === LIVE_ID;
}
