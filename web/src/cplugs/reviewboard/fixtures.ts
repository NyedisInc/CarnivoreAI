import type { BoardAnswer, BoardRevision, BoardRound, BoardSidecar } from './board-model';

export function revision(n: number, over: Partial<BoardRevision> = {}): BoardRevision {
  return {
    id: `r${n}`, n, created_at: `2026-10-13T14:0${n}:00Z`, summary: `summary of r${n}`, answers_round: null, viewport: 412,
    views: [{ id: 'main', label: 'main', file: `r00${n}.html` }], prompts: [{ id: 'layout', kind: 'choice', label: 'which row', anchor: 'buttons', options: [{ id: 'a', label: 'one row' }, { id: 'b', label: 'two rows' }] },
      { id: 'padding', kind: 'check', label: 'padding ok' }, { id: 'extra', kind: 'question', label: 'anything missing?' }],
    anchors: [{ id: 'buttons', label: 'button row' }], ...over,
  };
}

export function round(n: number, on: string, over: Partial<BoardRound> = {}): BoardRound {
  return {
    id: `n${n}`, n, revision: on, client_round_id: `00000000-0000-4000-8000-00000000000${n}`, sent_at: `2026-10-13T14:0${n}:30Z`, context: {},
    answers: [], anchor_notes: [], note: '', unanswered: [], delivery: { state: 'posted' }, ...over,
  };
}

export function boardAnswer(over: Partial<BoardSidecar> = {}): BoardAnswer {
  const sidecar: BoardSidecar = {
    board: { slug: '20261013-bottom-bar', title: 'bottom bar', kind: 'mockup' },
    task: { item_id: 41, computer: 'summit-m4' },
    revisions: [revision(1), revision(2), revision(3)],
    rounds: [round(1, 'r1')],
    ...over,
  };
  return { slug: sidecar.board.slug, status: 'ok', state: 'your_turn', etag: 'e', sidecar };
}
