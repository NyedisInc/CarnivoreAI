/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const stub = vi.hoisted(() => ({
  previewSchedule: vi.fn(),
  parseSchedule: vi.fn(),
  createAutomation: vi.fn(),
  updateAutomation: vi.fn(),
  listClaudeLogins: vi.fn(),
  listAnthropicKeys: vi.fn(),
}));
vi.mock('./api', () => stub);
vi.mock('../blueprints/api', () => ({ listBlueprints: vi.fn().mockResolvedValue({ status: 'ok', blueprints: [] }) }));

import AutomationEditor from './AutomationEditor.svelte';

const recipeTargets = {
  kinds: ['recipe', 'command', 'sequence', 'session_message'],
  commands: ['/usr/bin/git pull --ff-only'],
  recipes: [{ recipe: 'scrooge', params_schema: { properties: { active_days: { type: 'integer', default: 30, minimum: 1, maximum: 90 } } } }],
};
const projects = [{ id: 7, name: 'site', folder: '/x/site' }];
const saved = { automation_id: 'aut_3', name: 'x', revision: 1 };

let app: ReturnType<typeof mount> | null = null;
const settle = async () => {
  for (let i = 0; i < 6; i++) await tick();
  flushSync();
};
const q = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;

async function mountEditor(targets: unknown = recipeTargets): Promise<void> {
  app = mount(AutomationEditor, { target: document.body, props: { automation: null, targets: targets as never, projects, onDone: vi.fn(), onCancel: vi.fn() } });
  await settle();
}

beforeEach(() => {
  Object.values(stub).forEach((fn) => fn.mockReset());
  stub.previewSchedule.mockResolvedValue({ ok: true, fires: [] });
  stub.createAutomation.mockResolvedValue(saved);
  stub.listClaudeLogins.mockResolvedValue([]);
  stub.listAnthropicKeys.mockResolvedValue([]);
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

const type = async (selector: string, value: string) => {
  const el = q<HTMLInputElement | HTMLTextAreaElement>(selector);
  el.value = value;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  await settle();
};
const choose = async (selector: string, value: string) => {
  const el = q<HTMLSelectElement>(selector);
  el.value = value;
  el.dispatchEvent(new Event('change', { bubbles: true }));
  await settle();
};

test('the editor posts the exact body for a recipe automation', async () => {
  await mountEditor();
  await type('[data-auto-field="name"]', 'nightly scrooge');
  await type('[data-auto-field="cron"]', '0 3 * * *');
  q('[data-editor-save]').click();
  await settle();
  expect(stub.createAutomation).toHaveBeenCalledTimes(1);
  expect(stub.createAutomation.mock.calls[0]![0]).toEqual({
    name: 'nightly scrooge',
    cron: '0 3 * * *',
    target: { kind: 'recipe', recipe: 'scrooge', params: { active_days: 30 } },
    delivery: { notify: true, notify_on: 'failure' },
    enabled: true,
    description: '',
    project_id: null,
    misfire: 'run_once',
    retry_max: 0,
    retry_backoff_s: 300,
    max_runtime_s: null,
  });
});

test('a target kind the server does not list is not offered', async () => {
  await mountEditor({ kinds: ['recipe', 'agent', 'future_kind'], commands: [], recipes: recipeTargets.recipes });
  const offered = [...document.querySelectorAll('[data-target-kind] option')].map((o) => (o as HTMLOptionElement).value);
  expect(offered).toEqual(['recipe', 'agent']);
});

test('the editor sends the contract fields in minutes converted to seconds', async () => {
  await mountEditor();
  await type('[data-auto-field="name"]', 'tuned');
  await type('[data-auto-field="cron"]', '0 3 * * *');
  await type('[data-auto-field="description"]', 'keeps the folder fresh');
  await choose('[data-auto-field="project"]', '7');
  await choose('[data-auto-field="misfire"]', 'skip');
  await choose('[data-auto-field="retry_max"]', '2');
  await type('[data-auto-field="retry_backoff"]', '10');
  await type('[data-auto-field="max_runtime"]', '30');
  q('[data-editor-save]').click();
  await settle();
  expect(stub.createAutomation.mock.calls[0]![0]).toMatchObject({
    description: 'keeps the folder fresh', project_id: 7, misfire: 'skip', retry_max: 2, retry_backoff_s: 600, max_runtime_s: 1800,
  });
});

test('the command form offers only the allow-list and says so when it is empty', async () => {
  await mountEditor();
  await choose('[data-target-kind]', 'command');
  expect([...document.querySelectorAll('[data-command-select] option')].map((o) => (o as HTMLOptionElement).value)).toEqual(['', '/usr/bin/git pull --ff-only']);
  unmount(app!);
  document.body.innerHTML = '';
  await mountEditor({ ...recipeTargets, commands: [] });
  await choose('[data-target-kind]', 'command');
  expect(document.querySelector('[data-command-none]')).not.toBeNull();
  expect(document.querySelector('[data-command-select]')).toBeNull();
});

test('a sequence saves its steps and keeps two as the least', async () => {
  await mountEditor();
  await choose('[data-target-kind]', 'sequence');
  expect(document.querySelectorAll('[data-sequence-step]')).toHaveLength(2);
  expect(q<HTMLButtonElement>('[data-sequence-step="0"] [data-step-remove]').disabled).toBe(true);
  await choose('[data-sequence-step="0"] [data-command-select]', '/usr/bin/git pull --ff-only');
  await type('[data-auto-field="name"]', 'pull then report');
  await type('[data-auto-field="cron"]', '0 3 * * *');
  q('[data-editor-save]').click();
  await settle();
  const target = stub.createAutomation.mock.calls[0]![0].target;
  expect(target.kind).toBe('sequence');
  expect(target.steps.map((s: { kind: string }) => s.kind)).toEqual(['command', 'recipe']);
  expect(target.steps[0].command).toBe('/usr/bin/git pull --ff-only');
});

test('the form is the mockup editor in the mockup order, the target block after the description, save then cancel', async () => {
  await mountEditor();
  const form = q('[data-automation-editor]');
  const order = [...form.querySelectorAll('[data-auto-field="name"], [data-auto-field="cron"], [data-auto-field="notify"], [data-auto-field="description"], [data-editor-target-block], [data-editor-save], [data-editor-cancel]')].map(
    (el) => el.getAttribute('data-auto-field') ?? (el.hasAttribute('data-editor-target-block') ? 'block' : el.hasAttribute('data-editor-save') ? 'save' : 'cancel'),
  );
  expect(order).toEqual(['name', 'cron', 'notify', 'description', 'block', 'save', 'cancel']);
  const labels = [...form.querySelectorAll('.ap-pn-f > .oc-form-field > .oc-form-field__label')].map((l) => l.textContent);
  expect(labels).toEqual(['name', 'delivery', 'description']);
  expect(form.querySelector('[data-when] > [data-when-label]')?.textContent).toBe('when it runs');
  expect(form.querySelector('.pl-titlebar')).toBeNull();
  expect(form.querySelectorAll('.oc-card')).toHaveLength(1);
  expect(form.querySelector('[role="switch"]')).toBeNull();
  expect(q('[data-editor-save]').textContent?.trim()).toBe('create');
});

test('the delivery select saves none, failure, report or always, and the runtime field has a line of its own', async () => {
  await mountEditor();
  await type('[data-auto-field="name"]', 'quiet');
  await type('[data-auto-field="cron"]', '0 3 * * *');
  expect([...document.querySelectorAll('[data-auto-field="notify"] option')].map((o) => (o as HTMLOptionElement).value)).toEqual(['none', 'failure', 'report', 'always']);
  await choose('[data-auto-field="notify"]', 'none');
  expect(q('[data-auto-field="max_runtime"]').closest('.auto-fld')!.classList.contains('ap-pn-wide')).toBe(true);
  q('[data-editor-save]').click();
  await settle();
  expect(stub.createAutomation.mock.calls[0]![0].delivery).toEqual({ notify: false, notify_on: null });
});

const parsed = {
  ok: true,
  cron: '0 17 * * 2#3',
  fires: [{ utc: '2026-11-17T22:00:00Z', local: '2026-11-17T17:00:00-05:00', in_zone: '2026-11-17T17:00:00-05:00' }],
};
const press = (selector: string) => {
  q(selector).click();
  return settle();
};

test('in words: Enter posts the sentence and the zone, nothing is set until use this schedule, and create waits', async () => {
  stub.parseSchedule.mockResolvedValue(parsed);
  await mountEditor();
  await type('[data-auto-field="name"]', 'monthly');
  const before = q<HTMLInputElement>('[data-auto-field="cron"]').value;
  await type('[data-words-input]', 'every third tuesday at 5 pm');
  q('[data-words-input]').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
  await settle();
  expect(stub.parseSchedule).toHaveBeenCalledWith('every third tuesday at 5 pm', Intl.DateTimeFormat().resolvedOptions().timeZone);
  expect(q('[data-words-card]').textContent).toContain('the third tuesday of every month at 5:00 pm');
  expect(q<HTMLInputElement>('[data-auto-field="cron"]').value).toBe(before);
  expect(q<HTMLButtonElement>('[data-editor-save]').disabled).toBe(true);
  expect(q('[data-editor-blocked]').textContent).toContain('use this schedule');
  await press('[data-w-use]');
  expect(q<HTMLInputElement>('[data-auto-field="cron"]').value).toBe('0 17 * * 2#3');
  expect(q<HTMLButtonElement>('[data-editor-save]').disabled).toBe(false);
  await press('[data-editor-save]');
  expect(stub.createAutomation.mock.calls[0]![0].cron).toBe('0 17 * * 2#3');
});

test('in words: start over keeps the schedule, and no ai connection points to pick', async () => {
  stub.parseSchedule.mockResolvedValueOnce(parsed).mockResolvedValueOnce({ ok: false, reason: 'no_ai_connection' });
  await mountEditor();
  await type('[data-words-input]', 'x');
  await press('[data-w-read]');
  await press('[data-w-reset]');
  expect(q<HTMLInputElement>('[data-auto-field="cron"]').value).toBe('0 9 * * 1-5');
  expect(document.querySelector('[data-editor-blocked]')).toBeNull();
  await type('[data-words-input]', 'y');
  await press('[data-w-read]');
  expect(q('[data-words-refused="no_ai_connection"]').textContent).toContain('use pick');
  await press('[data-w-to-pick]');
  expect(q('[data-when]').getAttribute('data-mode')).toBe('pick');
});

test('pick composes the one cron value and reads a typed cron back', async () => {
  await mountEditor();
  await press('[data-w-mode="pick"]');
  await choose('[data-w="rep"]', 'nth');
  expect(q<HTMLInputElement>('[data-auto-field="cron"]').value).toBe('0 9 * * 2#3');
  await choose('[data-w="hour12"]', '5');
  await choose('[data-w="ap"]', 'pm');
  expect(q<HTMLInputElement>('[data-auto-field="cron"]').value).toBe('0 17 * * 2#3');
  await type('[data-auto-field="cron"]', '0 8 * * 1');
  expect(q<HTMLSelectElement>('[data-w="rep"]').value).toBe('days');
  expect(q<HTMLSelectElement>('[data-w="hour12"]').value).toBe('8');
  expect(q('[data-cron-preview]').textContent).toBeDefined();
});

test('an idea fills the form and create saves its schedule', async () => {
  await mountEditor();
  await press('[data-w-idea="6"]');
  expect(q<HTMLInputElement>('[data-auto-field="name"]').value).toBe('nightly status');
  expect(q<HTMLInputElement>('[data-auto-field="cron"]').value).toBe('0 2 * * *');
  await press('[data-editor-save]');
  const body = stub.createAutomation.mock.calls[0]![0];
  expect(body.name).toBe('nightly status');
  expect(body.cron).toBe('0 2 * * *');
  expect(body.target.command).toBe('git -C ~/dev status --short');
});

test('every field carries a hint and an example that fills it', async () => {
  await mountEditor();
  expect(['name', 'notify', 'description'].every((f) => document.querySelector(`[data-hint="${f}"]`))).toBe(true);
  await press('[data-hint="name"] [data-w-fill]');
  expect(q<HTMLInputElement>('[data-auto-field="name"]').value).toBe('morning digest');
  await press('[data-hint="description"] [data-w-fill]');
  expect(q<HTMLInputElement>('[data-auto-field="description"]').value).toBe('runs before standup');
});

test('every contract field shows a hint and its example fills the field', async () => {
  await mountEditor();
  for (const field of ['project', 'misfire', 'retry_max', 'retry_backoff', 'max_runtime']) expect(document.querySelector(`[data-hint="${field}"]`)).not.toBeNull();
  await press('[data-w-fill="retry_max"]');
  expect(q<HTMLSelectElement>('[data-auto-field="retry_max"]').value).toBe('2');
  await press('[data-w-fill="max_runtime"]');
  expect(q<HTMLInputElement>('[data-auto-field="max_runtime"]').value).toBe('30');
  await press('[data-w-fill="misfire"]');
  expect(q<HTMLSelectElement>('[data-auto-field="misfire"]').value).toBe('skip');
});

test('a yearly schedule lists its next runs with the year; a short one does not', async () => {
  const fire = (utc: string) => ({ utc, local: utc, in_zone: utc });
  stub.previewSchedule.mockResolvedValue({ ok: true, fires: ['2026-12-25T12:00:00Z', '2027-12-25T12:00:00Z', '2028-12-25T12:00:00Z'].map(fire) });
  await mountEditor();
  await type('[data-auto-field="cron"]', '0 9 25 12 *');
  await new Promise((r) => setTimeout(r, 700));
  await settle();
  const lines = [...document.querySelectorAll('[data-cron-preview] li')].map((l) => l.textContent);
  expect(lines.length).toBe(3);
  expect(lines[0]).toContain('2026');
  expect(lines[2]).toContain('2028');
  stub.previewSchedule.mockResolvedValue({ ok: true, fires: ['2026-12-25T12:00:00Z', '2026-12-26T12:00:00Z'].map(fire) });
  await type('[data-auto-field="cron"]', '0 9 * * *');
  await new Promise((r) => setTimeout(r, 700));
  await settle();
  expect(document.querySelector('[data-cron-preview] li')!.textContent).not.toContain('2026');
});
