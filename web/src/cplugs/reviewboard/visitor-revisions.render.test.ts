/** @vitest-environment jsdom */
import { afterEach, describe, expect, it } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { resetVisitorRevisions, type VisitorRevision, type VisitorRevisionAnswers } from './board-visitor-revisions.svelte';
import HistoryBar from './HistoryBar.svelte';
import { historyItems } from './board-model';
import { boardAnswer, revision } from './fixtures';
import Tray from './Tray.svelte';
import { payloadLines, promptWords, visitorsOf } from './visitor-lines';
import VisitorAnswers from './VisitorAnswers.svelte';
import VisitorToggle from './VisitorToggle.svelte';

const U1: VisitorRevisionAnswers = { label: 'u1', number: 1, revision: 'r1', body: { answers: [{ prompt: 'layout', options: ['b'] }] }, updated_at: 1 };
const U2: VisitorRevisionAnswers = { label: 'u2', number: 2, revision: 'r1', body: { answers: [{ prompt: 'padding', checked: true }] }, updated_at: 2 };
const U3: VisitorRevisionAnswers = { label: 'u3', number: 3, revision: 'r3', body: { answers: [] }, updated_at: 4 };

let app: ReturnType<typeof mount> | null = null;
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; resetVisitorRevisions(); });

describe('the model', () => {
  it('picks a revision\'s visitors in number order', () => {
    expect(visitorsOf([U3, U2, U1], 'r1').map((v) => v.label)).toEqual(['u1', 'u2']);
  });

  it('reads a prompt answer with the board\'s option labels, and nothing for an unanswered prompt', () => {
    const [layout, padding] = revision(1).prompts;
    expect(promptWords(layout!, U1.body, 'yes', 'no')).toBe('two rows');
    expect(promptWords(padding!, U2.body, 'yes', 'no')).toBe('yes');
    expect(promptWords(padding!, U1.body, 'yes', 'no')).toBe('');
  });

  it('reads a layer\'s payload in the layer\'s order with its labels and notes', () => {
    const rev = revision(2, { payload_mode: true, prompts: [], layer: { kind: 'rows', choices: [{ id: 'ok', label: 'keep' } as never], rows: [{ id: 'a', title: 'first' } as never, { id: 'b', title: 'second' } as never] } });
    const lines = payloadLines(rev, { payload: { layer: 'rows', v: 1, values: { b: 'ok' }, notes: { a: 'why' } } });
    expect(lines).toEqual([{ id: 'a', label: 'first', value: '', note: 'why' }, { id: 'b', label: 'second', value: 'keep', note: '' }]);
  });
});

describe('the history bar', () => {
  it('draws a u chip after the revision it answers, with no sent state, and opens it on a tap', () => {
    const opened: string[] = [];
    const items = historyItems(boardAnswer().sidecar!);
    app = mount(HistoryBar, { target: document.body, props: { items, folded: null, current: 'r1', total: 3, onpick: () => undefined, onunfold: () => undefined,
      visitors: [U1, U2, U3], openVisitor: 2, onvisitor: (row: VisitorRevision) => opened.push(row.label) } });
    flushSync();
    const marks = [...document.querySelectorAll<HTMLElement>('[data-history]')].map((el) => el.dataset.visitor ?? el.textContent?.trim());
    expect(marks.slice(0, 3)).toEqual(['r1', 'u1', 'u2']);
    expect(marks.indexOf('u3')).toBe(marks.indexOf('r3') + 1);
    const u2 = document.querySelector<HTMLButtonElement>('[data-visitor="u2"]')!;
    expect(u2.dataset.sent).toBeUndefined();
    expect(u2.getAttribute('aria-label')).not.toMatch(/sent/);
    expect(u2.getAttribute('aria-current')).toBe('true');
    expect(u2.querySelector('.rb-ubadge')?.textContent).toBe('u');
    u2.click();
    expect(opened).toEqual(['u2']);
  });
});

describe('a layer\'s answers', () => {
  it('lists them marked with the visitor badge and renders a planted tag as text', () => {
    const rev = revision(2, { payload_mode: true, prompts: [], layer: { kind: 'questions', items: [{ id: 'q', kind: 'text', label: 'why' } as never] } });
    const row: VisitorRevisionAnswers = { label: 'u1', number: 1, revision: 'r2', body: { payload: { layer: 'questions', v: 1, values: { q: '<img src=x onerror=alert(1)>' } } }, updated_at: 1 };
    app = mount(VisitorAnswers, { target: document.body, props: { revision: rev, row } });
    flushSync();
    expect(document.querySelector('[data-visitor-answers="u1"] .rb-ubadge')?.textContent).toBe('u1');
    expect(document.querySelector('[data-visitor-line="q"]')?.textContent).toContain('<img src=x onerror=alert(1)>');
    expect(document.querySelector('img')).toBeNull();
  });
});

describe('inline on the owner\'s side', () => {
  function tray(visitor: VisitorRevisionAnswers | null, on: 'newest' | 'r1' = 'newest'): void {
    const sidecar = boardAnswer().sidecar!;
    const shown = on === 'r1' ? sidecar.revisions[0]! : sidecar.revisions.at(-1)!;
    app = mount(Tray, { target: document.body, props: { sidecar, revision: shown, latest: sidecar.revisions.at(-1)!, draft: null, phase: 'your_turn', pointed: null,
      confirm: null, sending: false, failed: false, visitor, onedit: () => undefined, onsend: () => undefined, onclear: () => undefined, onmove: () => undefined,
      onround: () => undefined } });
    flushSync();
  }

  it('shows the visitor\'s answer under each prompt of an older revision, marked with the badge, and "no answer" where there is none', () => {
    tray(U1, 'r1');
    expect(document.querySelector('[data-visitor-line="layout"]')?.textContent).toBe('u1two rows');
    expect(document.querySelector('[data-visitor-line="layout"] .rb-ubadge')?.textContent).toBe('u1');
    expect(document.querySelector('[data-visitor-line="padding"]')?.textContent).toBe('u1no answer');
  });

  it('shows the line under the owner\'s own control on the newest revision', () => {
    tray({ ...U3, body: { answers: [{ prompt: 'extra', text: 'more space' }] } });
    expect(document.querySelector('[data-visitor-line="extra"]')?.textContent).toBe('u3more space');
    expect(document.querySelector('[data-visitor-line="layout"]')?.textContent).toBe('u3no answer');
  });

  it('shows nothing of a visitor who answered another revision, or of none', () => {
    tray(U3, 'r1');
    expect(document.querySelector('[data-visitor-line]')).toBeNull();
    unmount(app!); app = null;
    tray(null);
    expect(document.querySelector('[data-visitor-line]')).toBeNull();
  });

  it('the toggle lists the revision\'s visitors and picks one, or none', () => {
    const picked: Array<number | null> = [];
    app = mount(VisitorToggle, { target: document.body, props: { rows: [U1, U2], value: null, onchange: (n: number | null) => picked.push(n) } });
    flushSync();
    const select = document.querySelector<HTMLSelectElement>('[data-visitor-toggle]')!;
    expect([...select.options].map((o) => o.textContent)).toEqual(['none', 'u1', 'u2']);
    select.value = '2'; select.dispatchEvent(new Event('change', { bubbles: true }));
    select.value = ''; select.dispatchEvent(new Event('change', { bubbles: true }));
    expect(picked).toEqual([2, null]);
  });
});
