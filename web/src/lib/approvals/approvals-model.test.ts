import { describe, expect, it } from 'vitest';
import {
  answerBody, badgeCount, hostName, isRemote, isWholeAsk, isStartupDialog, offersDismiss, optionRows, optionTone, refusalReason,
  sessionNameFor, startupReadOnlyReason, targetNameFor, type ApprovalItem,
} from './approvals-model';
import { TMUX_SESSION_PREFIX } from '../product-identity';

const item: ApprovalItem = {
  id: 'd1', source: 'dialog', host: 'local', session_id: 'ses_1', fingerprint: 'f'.repeat(64),
  rows: [{ label: 'yes', role: 'option' }, { label: 'type something', role: 'other' }, { label: 'submit', role: 'submit' }],
};

describe('approvals model', () => {
  it('lists only option rows', () => expect(optionRows(item).map((r) => r.label)).toEqual(['yes']));
  it('tells a remote host from local', () => {
    expect(isRemote(item)).toBe(false);
    expect(isRemote({ ...item, host: 'peer-abc' })).toBe(true);
  });
  it('names a remote item by its computer, short id only as a fallback', () => {
    const raw = 'peer-4D3F86DB2AE6CF5F23E5';
    expect(hostName({ ...item, host: raw, host_label: 'studio' })).toBe('studio');
    expect(hostName({ ...item, host: raw })).toBe('peer-4D3F86DB...');
    expect(hostName({ ...item, host: raw, host_label: raw.toLowerCase() })).toBe('peer-4D3F86DB...');
  });
  it('builds the answer body with the fingerprint', () => {
    expect(answerBody(item, { option: 'yes' })).toEqual({ fingerprint: 'f'.repeat(64), choice: { option: 'yes' } });
  });
  it('reads a 409 reason and nothing else', () => {
    expect(refusalReason({ detail: { reason: 'dialog_changed' } })).toBe('dialog_changed');
    expect(refusalReason({ detail: 'nope' })).toBeNull();
    expect(refusalReason(null)).toBeNull();
  });
  it('hides the badge at zero and on garbage', () => {
    expect(badgeCount(0)).toBeNull();
    expect(badgeCount(Number.NaN)).toBeNull();
    expect(badgeCount(1)).toBe(1);
  });
  it('names current and legacy panes without a listing while refusing unnamed external handles', () => {
    expect(sessionNameFor(`${TMUX_SESSION_PREFIX}caller`, [])).toBe('caller');
    expect(sessionNameFor('cloude_old', [])).toBe('old');
    expect(sessionNameFor('external-pane', [])).toBeNull();
    expect(sessionNameFor(`${TMUX_SESSION_PREFIX}caller`, [{ tmux_session: `${TMUX_SESSION_PREFIX}caller`, label: 'my caller' }])).toBe('my caller');
    expect(targetNameFor({ id: 'a1', source: 'agent_action', tmux_session: `${TMUX_SESSION_PREFIX}target` }, [])).toBe('target');
  });
});

import { createdMs, oldestFirst } from './approvals-model';

describe('oldestFirst', () => {
  const mk = (id: string, created_at?: number | string | null) => ({ id, source: 'dialog' as const, created_at });

  it('sorts oldest first, accepts seconds, ms and ISO, and keeps undated items last in server order', () => {
    const order = oldestFirst([mk('none-a'), mk('new', 1_700_000_300), mk('old', '2023-11-14T22:13:20Z'), mk('none-b', null), mk('mid', 1_700_000_100_000)]);
    expect(order.map((i) => i.id)).toEqual(['old', 'mid', 'new', 'none-a', 'none-b']);
  });

  it('reads no time from junk', () => {
    expect(createdMs(mk('x', 'not a date'))).toBeNull();
  });
});

describe('every prompt shows its own options (Joe (ccsliinc), 2026-10-09)', () => {
  const base = { source: 'dialog' as const, host: 'local', session_id: 'ses_1', fingerprint: 'f'.repeat(64) };
  const kinds: [string, ApprovalItem, string[]][] = [
    ['a permission prompt with a "Yes, and ..." row', { ...base, id: 'p', kind: 'permission',
      rows: [{ label: 'Yes', role: 'option' }, { label: "Yes, and don't ask again", role: 'option' }, { label: 'No', role: 'option' }] },
      ['Yes', "Yes, and don't ask again", 'No']],
    ['a question with several options and a free-text row', { ...base, id: 'q', kind: 'ask_user_question',
      rows: [{ label: 'Red', role: 'option' }, { label: 'Blue', role: 'option' }, { label: 'Type something.', role: 'other' }, { label: 'Chat about this', role: 'chat' }] },
      ['Red', 'Blue']],
    ['a plan approval', { ...base, id: 'pl', kind: 'plan_approval',
      rows: [{ label: 'Yes, and auto-accept edits', role: 'option' }, { label: 'Yes, and manually approve edits', role: 'option' }, { label: 'No, keep planning', role: 'option' }] },
      ['Yes, and auto-accept edits', 'Yes, and manually approve edits', 'No, keep planning']],
    ['a multi-select', { ...base, id: 'm', kind: 'ask_user_question', multi_select: true,
      rows: [{ label: 'A', role: 'option', checked: false }, { label: 'B', role: 'option', checked: true }, { label: 'Submit', role: 'submit' }] },
      ['A', 'B']],
    ['the folder-trust variant', { ...base, id: 't', kind: 'folder_trust', startup_kind: 'trust',
      rows: [{ label: 'No, continue without these permissions', role: 'option' }, { label: 'Yes, I trust this folder', role: 'option' }] },
      ['No, continue without these permissions', 'Yes, I trust this folder']],
    ['an mcp server screen', { ...base, id: 'mcp', kind: 'other', startup_kind: 'mcp_server',
      rows: [{ label: 'Use this MCP server', role: 'option' }, { label: 'Use this and all future MCP servers in this project', role: 'option' }, { label: 'Continue without using this MCP server', role: 'option' }] },
      ['Use this MCP server', 'Use this and all future MCP servers in this project', 'Continue without using this MCP server']],
  ];

  it.each(kinds)('%s lists every option in screen order', (_name, it_, labels) => {
    expect(optionRows(it_).map((r) => r.label)).toEqual(labels);
  });

  it('a decoded startup screen is a startup dialog with no dismiss', () => {
    const trust = kinds[4]![1];
    expect(isStartupDialog(trust)).toBe(true);
    expect(offersDismiss(trust)).toBe(false);
  });

  it('any other dialog keeps its dismiss', () => {
    const permission = kinds[0]![1];
    expect(isStartupDialog(permission)).toBe(false);
    expect(offersDismiss(permission)).toBe(true);
    expect(isStartupDialog({ ...permission, startup_kind: null })).toBe(false);
  });

  it('a read-only startup item is never a startup dialog and has no dismiss', () => {
    const readOnly: ApprovalItem = { id: 'sp', source: 'startup_prompt', kind: 'trust', rows: [] };
    expect(isStartupDialog(readOnly)).toBe(false);
    expect(offersDismiss(readOnly)).toBe(false);
    expect(optionRows(readOnly)).toEqual([]);
  });

  it.each([
    ['oauth_login', 'browser'], ['login_method', 'browser'], ['resume_picker', 'picker'], ['onboarding_theme', 'picker'],
    ['trust', 'unread'], ['mcp_server', 'unread'], ['unrecognized', 'unread'], [undefined, 'unread'],
  ])('a read-only %s screen says %s', (kind, reason) => {
    expect(startupReadOnlyReason(kind)).toBe(reason);
  });

  it.each([
    ['No, exit', 'danger'], ['Exit', 'danger'], ['no,  exit', 'danger'],
    ['No', 'secondary'], ['No, continue without these permissions', 'secondary'], ['Yes, I trust this folder', 'secondary'],
    ['Exit plan mode', 'secondary'],
  ])('the option %s is drawn %s', (label, tone) => {
    expect(optionTone(label)).toBe(tone);
  });
});

describe('the whole-ask modal needs the questions the server matched', () => {
  const ask = { source: 'dialog' as const, host: 'peer-a', session_id: 'remote:peer-a:x', kind: 'ask_user_question', fingerprint: 'f'.repeat(64) };
  it('offers the batch for a paired computer ask that carries its questions', () => {
    const q = [{ header: 'h', question: 'q?', multi_select: false, options: [{ label: 'a' }] }];
    expect(isWholeAsk({ ...ask, id: 'r1', questions_state: 'matched', questions: q, questions_fingerprint: 'q'.repeat(64) } as ApprovalItem)).toBe(true);
  });
  it('falls back to the per-question card for an older build that sends none', () => {
    expect(isWholeAsk({ ...ask, id: 'r2' } as ApprovalItem)).toBe(false);
  });
});
