
import { describe, expect, test } from 'vitest';
import { createLayoutStore } from './layout.svelte';
import { instanceId } from './meta';
import { instancesOf } from './model';
import {
  PRIMARY_BIND_EVENT,
  duplicatesOf,
  reconcilePrimaryBind,
  watchPrimaryBind,
} from './primary-bind';
import type { LayoutStore } from './layout.svelte';
import type { SlotId } from './types';

function slots(store: LayoutStore): string[] {
  return instancesOf(store.state.layout).map((id) => id as string);
}

function surfaceWith(...sessionIds: string[]): LayoutStore {
  const store = createLayoutStore('terminal');
  for (const id of sessionIds) {
    const refusal = store.add('terminal', id);
    expect(refusal, `the fixture could not add a cell for ${id}`).toBeNull();
  }
  return store;
}

describe('the pane binding a session a cell is already showing', () => {
  test('the cell for that session comes off, and only that one', () => {
    const store = surfaceWith('ses_a', 'ses_b');
    expect(slots(store)).toContain(instanceId('terminal', 'ses_a') as string);

    const removed = reconcilePrimaryBind(store, 'ses_a');

    expect(removed).toBe(1);
    expect(slots(store)).not.toContain(instanceId('terminal', 'ses_a') as string);
    expect(slots(store)).toContain(instanceId('terminal', 'ses_b') as string);
  });

  test('binding a session no cell shows changes nothing', () => {
    const store = surfaceWith('ses_a', 'ses_b');
    const before = slots(store);
    expect(reconcilePrimaryBind(store, 'ses_c')).toBe(0);
    expect(slots(store)).toEqual(before);
  });

  test('the primary slot is never what comes off', () => {
    const store = surfaceWith('ses_a');
    const primary = store.state.layout.rows.flatMap((row) => row.slots.map((s) => s.id));
    expect(primary).toContain('terminal:@primary');
    reconcilePrimaryBind(store, '@primary');
    reconcilePrimaryBind(store, 'ses_a');
    const after = store.state.layout.rows.flatMap((row) => row.slots.map((s) => s.id));
    expect(after).toContain('terminal:@primary');
  });

  test('an empty session id is not a statement and removes nothing', () => {
    const store = surfaceWith('ses_a');
    expect(duplicatesOf(store, '')).toEqual([]);
    expect(reconcilePrimaryBind(store, '   ')).toBe(0);
    expect(slots(store)).toContain(instanceId('terminal', 'ses_a') as string);
  });

  test('the home surface is left alone', () => {
    const home = createLayoutStore('home');
    home.add('terminal', 'ses_a');
    const before = slots(home);
    expect(before).toContain(instanceId('terminal', 'ses_a') as string);
    expect(reconcilePrimaryBind(home, 'ses_a')).toBe(0);
    expect(slots(home)).toEqual(before);
  });
});

describe('the announcement the classic script makes', () => {
  test('a dispatched bind event takes the duplicate down', () => {
    const store = surfaceWith('ses_a', 'ses_b');
    const bus = new EventTarget();
    const stop = watchPrimaryBind(store, bus);

    bus.dispatchEvent(
      new CustomEvent(PRIMARY_BIND_EVENT, { detail: { sessionId: 'ses_a' } }),
    );
    expect(slots(store)).not.toContain(instanceId('terminal', 'ses_a') as string);
    expect(slots(store)).toContain(instanceId('terminal', 'ses_b') as string);

    stop();
    bus.dispatchEvent(
      new CustomEvent(PRIMARY_BIND_EVENT, { detail: { sessionId: 'ses_b' } }),
    );
    expect(slots(store)).toContain(instanceId('terminal', 'ses_b') as string);
  });

  test('an event with no detail is survived rather than thrown on', () => {
    const store = surfaceWith('ses_a');
    const bus = new EventTarget();
    watchPrimaryBind(store, bus);
    expect(() => bus.dispatchEvent(new Event(PRIMARY_BIND_EVENT))).not.toThrow();
    expect(slots(store)).toContain(instanceId('terminal', 'ses_a') as string);
  });

  test('ONLY the page\'s own pane announces, never a cell\'s client', () => {
    const fs = require('node:fs') as typeof import('node:fs');
    const path = require('node:path') as typeof import('node:path');
    const vm = require('node:vm') as typeof import('node:vm');
    const src = fs.readFileSync(
      path.resolve(__dirname, '..', '..', '..', '..', 'client', 'js', 'terminal-session-bind.js'),
      'utf8',
    );
    const said: string[] = [];
    const sandbox: Record<string, unknown> = {
      console: { log() {}, warn() {} },
      CustomEvent: class {
        type: string;
        detail: unknown;
        constructor(type: string, init?: { detail?: unknown }) {
          this.type = type;
          this.detail = init?.detail;
        }
      },
      dispatchEvent: (ev: { detail?: { sessionId?: string } }) => {
        said.push(ev.detail?.sessionId ?? '');
        return true;
      },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(src, sandbox, { filename: 'terminal-session-bind.js' });
    const bind = sandbox.TerminalSessionBind as {
      announce(controller: unknown, id: string): boolean;
    };

    const pane = { name: 'the page pane' };
    const cell = { name: 'a cell client' };
    sandbox.TerminalController = pane;

    expect(bind.announce(cell, 'ses_b'), 'a cell client announced').toBe(false);
    expect(bind.announce(null, 'ses_b')).toBe(false);
    expect(said).toEqual([]);

    expect(bind.announce(pane, 'ses_a'), 'the page pane was refused too').toBe(true);
    expect(said).toEqual(['ses_a']);
    expect(bind.announce(pane, '   ')).toBe(false);
    expect(said).toEqual(['ses_a']);
  });

  test('the two trees spell the event the same way', () => {
    const fs = require('node:fs') as typeof import('node:fs');
    const path = require('node:path') as typeof import('node:path');
    const src = fs.readFileSync(
      path.resolve(__dirname, '..', '..', '..', '..', 'client', 'js', 'terminal-session-bind.js'),
      'utf8',
    );
    const m = src.match(/var EVENT = '([^']+)'/);
    expect(m, 'terminal-session-bind.js no longer declares EVENT as a literal').toBeTruthy();
    expect(m![1]).toBe(PRIMARY_BIND_EVENT);
    const term = fs.readFileSync(
      path.resolve(__dirname, '..', '..', '..', '..', 'client', 'js', 'terminal.js'),
      'utf8',
    );
    expect(term).toMatch(/TerminalSessionBind\.announce\(this,/);
  });
});
