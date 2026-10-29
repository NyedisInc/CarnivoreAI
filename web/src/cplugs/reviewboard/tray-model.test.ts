import { describe, expect, it } from 'vitest';
import type { BoardPrompt } from './board-model';
import { boardAnswer, revision, round } from './fixtures';
import {
  anchorNoteOf, answerOf, draftCounts, anchorState, carryDraft, copyGhost, ghostFor, isDraftEmpty, newDraft, pickOption, roundBody, setAnchorNote, setChecked,
  setNote, setPromptNote, setText, unansweredCount,
} from './tray-model';

const layout: BoardPrompt = { id: 'layout', kind: 'choice', label: 'which row', anchor: 'buttons', options: [{ id: 'a', label: 'one row' }, { id: 'b', label: 'two rows' }] };
const multi: BoardPrompt = { id: 'pick', kind: 'multi', label: 'which', options: [{ id: 'x', label: 'x' }, { id: 'y', label: 'y' }] };
const padding: BoardPrompt = { id: 'padding', kind: 'check', label: 'padding ok' };
const extra: BoardPrompt = { id: 'extra', kind: 'question', label: 'anything missing?' };

describe('editing a draft', () => {
  it('a choice holds one option and a second tap on it clears it', () => {
    let d = pickOption(newDraft('r3', 'id'), layout, 'a');
    d = pickOption(d, layout, 'b');
    expect(answerOf(d, 'layout')?.options).toEqual(['b']);
    expect(answerOf(pickOption(d, layout, 'b'), 'layout')).toBeNull();
  });

  it('a multi toggles, a check keeps false as an answer, a blank question clears', () => {
    let d = pickOption(pickOption(newDraft('r3'), multi, 'x'), multi, 'y');
    expect(answerOf(d, 'pick')?.options).toEqual(['x', 'y']);
    d = pickOption(d, multi, 'x');
    expect(answerOf(d, 'pick')?.options).toEqual(['y']);
    d = setChecked(d, padding, false);
    expect(answerOf(d, 'padding')?.checked).toBe(false);
    d = setText(d, extra, '  needs warning ');
    expect(answerOf(d, 'extra')?.text).toBe('  needs warning ');
    expect(answerOf(setText(d, extra, '   '), 'extra')).toBeNull();
  });

  it('a prompt note needs an answer, anchor notes and the general note are kept as typed, and emptiness is exact', () => {
    let d = newDraft('r3');
    expect(setPromptNote(d, layout, 'x')).toBe(d);
    expect(isDraftEmpty(d)).toBe(true);
    d = setPromptNote(pickOption(d, layout, 'a'), layout, 'because');
    expect(answerOf(d, 'layout')?.note).toBe('because');
    d = setAnchorNote(d, 'send', 'too close');
    expect(anchorNoteOf(d, 'send')).toBe('too close');
    expect(setAnchorNote(d, 'send', ' ').anchor_notes).toEqual([]);
    expect(isDraftEmpty(setNote(newDraft('r3'), 'hi'))).toBe(false);
  });

  it('counts unanswered prompts and tells the frame which anchors are done', () => {
    const rev = revision(3, { prompts: [layout, padding], anchors: [{ id: 'buttons', label: 'b' }, { id: 'send', label: 's' }] });
    const d = setAnchorNote(pickOption(newDraft('r3'), layout, 'a'), 'send', 'x');
    expect(unansweredCount(rev, d)).toBe(1);
    expect(unansweredCount(rev, null)).toBe(2);
    expect(anchorState(rev, d)).toEqual({ answered: ['buttons'], noted: ['send'] });
  });

  it('builds the send body from the draft and the context', () => {
    const d = setNote(pickOption(newDraft('r2', 'abc'), layout, 'b'), 'ok');
    expect(roundBody(d, { width: 412, fit: 'actual' })).toEqual({
      client_round_id: 'abc', revision: 'r2', answers: d.answers, anchor_notes: [], note: 'ok', context: { width: 412, fit: 'actual' },
    });
  });
});

describe('ghost lines', () => {
  const sidecar = boardAnswer({ rounds: [round(1, 'r1', { answers: [{ prompt: 'layout', options: ['b'], note: '' }] })] }).sidecar!;

  it('shows the last answer to a prompt id asked again, never one from the same or a later revision', () => {
    expect(ghostFor(sidecar, layout, 2)).toMatchObject({ round: 'n1', revision: 'r1' });
    expect(ghostFor(sidecar, layout, 1)).toBeNull();
    expect(ghostFor(sidecar, extra, 3)).toBeNull();
  });

  it('copies only on request and only when the option still exists; it is never pre-ticked', () => {
    const d = newDraft('r2');
    expect(answerOf(d, 'layout')).toBeNull();
    const ghost = ghostFor(sidecar, layout, 2)!;
    expect(answerOf(copyGhost(d, layout, ghost), 'layout')?.options).toEqual(['b']);
    const changed: BoardPrompt = { ...layout, options: [{ id: 'a', label: 'a' }] };
    expect(copyGhost(d, changed, ghost)).toBe(d);
  });
});

describe('a revision that landed while the owner wrote', () => {
  it('carries answers that still fit and turns the rest into words in the note', () => {
    const from = revision(2, { prompts: [layout, extra], anchors: [{ id: 'send', label: 'send button' }] });
    const to = revision(3, { prompts: [{ ...layout, options: [{ id: 'a', label: 'a' }] }, extra], anchors: [{ id: 'buttons', label: 'b' }] });
    let d = setNote(pickOption(newDraft('r2', 'keep'), layout, 'b'), 'hello');
    d = setAnchorNote(setText(d, extra, 'warn'), 'send', 'close');
    const moved = carryDraft(d, from, to);
    expect(moved).toMatchObject({ revision: 'r3', client_round_id: 'keep' });
    expect(moved.answers.map((a) => a.prompt)).toEqual(['extra']);
    expect(moved.note).toContain('hello');
    expect(moved.note).toContain('which row: b');
    expect(moved.note).toContain('send button: close');
    expect(moved.anchor_notes).toEqual([]);
  });
});

describe('draftCounts', () => {
  const rev = revision(3, { prompts: [layout, padding, extra] });

  it('counts answers, what is left and every kind of note; a free-text answer is not a note', () => {
    let d = newDraft('r3');
    d = pickOption(d, layout, 'a');
    d = setText(d, extra, 'words');
    d = setPromptNote(d, layout, 'why');
    d = setAnchorNote(d, 'buttons', 'pin');
    d = setNote(d, 'general');
    expect(draftCounts(rev, d)).toEqual({ answered: 2, left: 1, noted: 3 });
    expect(draftCounts(rev, null)).toEqual({ answered: 0, left: 3, noted: 0 });
  });
});
