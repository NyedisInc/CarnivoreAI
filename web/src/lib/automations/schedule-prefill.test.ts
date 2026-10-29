import { describe, expect, it, test, vi } from 'vitest';
import { editorStart, openScheduleThis, parsePrefill, scheduleHash } from './schedule-prefill';

test('the fragment round-trips for a session and a project', () => {
  expect(scheduleHash({ kind: 'session', id: 'abc-123' })).toBe('#automations/new/session/abc-123');
  expect(parsePrefill('#automations/new/session/abc-123')).toEqual({ kind: 'session', id: 'abc-123' });
  expect(parsePrefill(scheduleHash({ kind: 'project', id: 7 }))).toEqual({ kind: 'project', id: 7 });
});

test('a fragment that names no node names nothing', () => {
  for (const hash of ['', '#automations', '#automations/run/r1', '#automations/new/project/x', '#automations/new/session/../x', '#automations/new/session/a b', null, undefined]) {
    expect(parsePrefill(hash as string)).toBeNull();
  }
});

test('a session prefill is a message to that uuid, in the session project when the project is a choice', () => {
  const projects = [{ id: 7, name: 'site', folder: '/x' }];
  const sessions = [{ session_uuid: 'u-1', name: 'api work', project_id: 7 }];
  const start = editorStart({ kind: 'session', id: 'u-1' }, null, sessions, projects);
  expect(start.projectId).toBe(7);
  expect(start.target).toMatchObject({ kind: 'session_message', session_uuid: 'u-1', session_name: 'api work', project_id: 7, if_asleep: 'wake', if_gone: 'start' });
  const unknown = editorStart({ kind: 'session', id: 'u-9' }, null, sessions, projects);
  expect(unknown.projectId).toBeNull();
  expect(unknown.target).toMatchObject({ session_uuid: 'u-9', session_name: '', project_id: null });
});

test('a project prefill sets the project, and the target only when the target has a project field', () => {
  const withField = editorStart({ kind: 'project', id: 7 }, { kind: 'command', command: '', project_id: null }, [], []);
  expect(withField).toEqual({ target: { kind: 'command', command: '', project_id: 7 }, projectId: 7, name: '' });
  const recipe = { kind: 'recipe', recipe: 'scrooge', params: {} };
  expect(editorStart({ kind: 'project', id: 7 }, recipe, [], []).target).toEqual(recipe);
});

test('openScheduleThis writes the fragment and opens the page', () => {
  const open = vi.fn(() => true);
  const host = { location: { hash: '' }, CloudeWeb: { openAutomationsScreen: open } };
  expect(openScheduleThis({ kind: 'project', id: 3 }, host)).toBe(true);
  expect(host.location.hash).toBe('#automations/new/project/3');
  expect(open).toHaveBeenCalledOnce();
  expect(openScheduleThis({ kind: 'project', id: 3 }, { location: { hash: '' } })).toBe(false);
});

describe('open this automation (the automations widgets)', () => {
  it('writes and reads the edit fragment, and ignores everything else', async () => {
    const { openAutomationEdit, parseEditId } = await import('./schedule-prefill');
    const host = { location: { hash: '' }, CloudeWeb: { openAutomationsScreen: () => true } };
    expect(openAutomationEdit('auto_ab12', host)).toBe(true);
    expect(host.location.hash).toBe('#automations/edit/auto_ab12');
    expect(parseEditId(host.location.hash)).toBe('auto_ab12');
    expect(parseEditId('#automations/new/session/abc')).toBeNull();
    expect(parseEditId('#automations/edit/../x')).toBeNull();
    expect(parseEditId(null)).toBeNull();
  });
});

describe('the session focus fragment (a task item)', () => {
  test('names the session the automations page opens at', async () => {
    const { parseSessionFocus, openSessionAutomations } = await import('./schedule-prefill');
    expect(parseSessionFocus('#automations/session/8f1c-22ab')).toBe('8f1c-22ab');
    expect(parseSessionFocus('#automations/session/')).toBeNull();
    expect(parseSessionFocus('#automations/new/session/abc')).toBeNull();
    const opened: string[] = [];
    const host = { location: { hash: '' }, CloudeWeb: { openAutomationsScreen: () => { opened.push('open'); return true; } } };
    expect(openSessionAutomations('abc-1', host)).toBe(true);
    expect(host.location.hash).toBe('#automations/session/abc-1');
    expect(opened).toEqual(['open']);
  });
});

describe('the sessions tab fragment (#1798)', () => {
  test('names only the sessions tab', async () => {
    const { isSessionsTabHash } = await import('./schedule-prefill');
    expect(isSessionsTabHash('#automations/sessions')).toBe(true);
    for (const hash of ['#automations', '#automations/session/abc', '#automations/sessions/x', '', null, undefined]) expect(isSessionsTabHash(hash as string)).toBe(false);
  });
});

describe('the run fragments (B1, B2)', () => {
  test('parseRunLink and parseFeedRun each read only their own fragment', async () => {
    const { parseRunLink, parseFeedRun } = await import('./schedule-prefill');
    expect(parseRunLink('#automations/run/run_ab-12')).toBe('run_ab-12');
    expect(parseRunLink('#automations/sessions/run/run_ab')).toBeNull();
    expect(parseFeedRun('#automations/sessions/run/run_ab-12')).toBe('run_ab-12');
    expect(parseFeedRun('#automations/run/run_ab')).toBeNull();
    for (const hash of ['#automations', '#automations/sessions', '#automations/sessions/run/', '', null, undefined]) expect(parseFeedRun(hash as string)).toBeNull();
  });
});
