import { beforeEach, describe, expect, test } from 'vitest';
import { approvals, questionPending } from '../approvals/approvals.svelte';
import { attentionRows, bellRows } from './read.svelte';
import type { ApprovalItem } from '../approvals/approvals-model';

const item = (id: string, kind: string): ApprovalItem => ({ id, source: 'dialog', kind, session_id: `ses_${id}`, question: 'q?' }) as ApprovalItem;

beforeEach(() => { approvals.items = []; });

describe('bellRows', () => {
  test('an ask_user_question is no bell row, a permission dialog is', () => {
    approvals.items = [item('ask', 'ask_user_question'), item('perm', 'permission')];
    expect(bellRows().map((r) => r.key)).toEqual(['approval:perm']);
  });

  test('the questions slide-out source keeps the question, and it still counts as pending', () => {
    approvals.items = [item('ask', 'ask_user_question')];
    expect(attentionRows().map((r) => r.key)).toEqual(['approval:ask']);
    expect(bellRows()).toEqual([]);
    expect(questionPending()).toBe(true);
  });

  test('nothing waiting is not pending', () => {
    expect(questionPending()).toBe(false);
  });
});
