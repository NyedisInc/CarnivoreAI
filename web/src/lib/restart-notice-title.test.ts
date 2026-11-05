import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';

const JS = path.resolve(__dirname, '../../../client/js');
const click = fs.readFileSync(path.join(__dirname, 'drawer/restart-click.ts'), 'utf8');
const catalog = fs.readFileSync(path.join(JS, 'i18n/catalog.en.js'), 'utf8');

const callsFor = (key: string): string[] => click.split('\n').filter((line) => line.includes(`notifyFailure(name, '${key}'`));

describe('restart failure notices', () => {
  it('put a problem after a successful restart under the warning heading', () => {
    for (const key of ['session.restart.choice_not_saved', 'session.restart.reopen_failed']) {
      const calls = callsFor(key);
      expect(calls.length, key).toBe(1);
      expect(calls[0], key).toContain('RESTARTED_WITH_PROBLEM');
    }
    expect(click).toContain("RESTARTED_WITH_PROBLEM = 'notice.restart_warning.title'");
    expect(catalog).toContain("'notice.restart_warning.title': 'restarted, with a problem'");
  });

  it('keeps the failure heading for a restart that did not happen', () => {
    const failed = click.split('\n').filter((line) => line.includes('notifyFailure(name, failedKey'));
    expect(failed.length).toBeGreaterThan(0);
    for (const line of failed) expect(line).not.toContain('RESTARTED_WITH_PROBLEM');
    expect(click).toContain("'session.restart.card_failed'");
    expect(click).toContain("'session.recreate.failed'");
  });

  it('has no catalog entry that is only its {detail}', () => {
    expect(catalog).not.toMatch(/'session\.restart\.server_detail'/);
    expect(catalog).toMatch(/'session\.restart\.reopen_failed': '[^']*\{name\}[^']*\{detail\}/);
  });
});

describe('the notice module is optional at load and at the failure path', () => {
  it('loads and exports runRestart when WriteFailureNotice is absent, and a failure then logs instead of throwing (RED WHEN: a read of it throws)', async () => {
    const { runRestart } = await import('./drawer/restart-click');
    expect(typeof runRestart).toBe('function');
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    await runRestart({}, 'demo', null, 'local');
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});

describe('the string catalog', () => {
  it('names every restart key once, so a later entry never shadows an earlier one with other parameters (RED WHEN: two entries share a key)', () => {
    const keys = [...catalog.matchAll(/^ {4}'(session\.(?:restart|recreate)\.[a-z_]+)':/gm)].map((m) => m[1]);
    expect(keys.filter((k, i) => keys.indexOf(k) !== i)).toEqual([]);
  });
});
