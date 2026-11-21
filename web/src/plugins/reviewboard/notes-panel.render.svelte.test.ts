/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import NotesPanel from './NotesPanel.svelte';
import { MAX_NOTE, NoteKeeper, SIZE_KEY, noteKey, readNote } from './note-store';

const KEY = noteKey('20261013-bottom-bar', 'r3');
const HEADER_CSS = fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), 'header.css'), 'utf8');

let app: ReturnType<typeof mount> | null = null;
const host = $state({ value: '' });
const typedSpy = vi.fn();

async function draw(): Promise<void> {
  app = mount(NotesPanel, {
    target: document.body,
    props: {
      get value() { return host.value; },
      oninput: (text: string) => { typedSpy(text); host.value = text; },
      onclose: () => {},
      placeholder: 'a note for claude',
    },
  });
  for (let i = 0; i < 3; i += 1) {
    await tick();
    flushSync();
  }
}
const q = <T extends Element = HTMLElement>(sel: string): T => document.querySelector(sel) as T;
function type(text: string): void {
  const box = q<HTMLTextAreaElement>('[data-notes-panel] textarea');
  box.value = text;
  box.dispatchEvent(new Event('input', { bubbles: true }));
  flushSync();
}

beforeEach(() => {
  localStorage.clear();
  host.value = '';
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  document.body.replaceChildren();
  typedSpy.mockClear();
});

describe('the notes panel', () => {
  it('opens pinned top right at the remembered size, resizable, with the markdown editor and its cheat sheet', async () => {
    localStorage.setItem(SIZE_KEY, JSON.stringify({ width: 520, height: 410 }));
    await draw();
    const panel = q('[data-notes-panel]');
    expect(panel.classList.contains('rb-notes')).toBe(true);
    expect(panel.style.getPropertyValue('--rb-notes-w')).toBe('520px');
    expect(panel.style.getPropertyValue('--rb-notes-h')).toBe('410px');
    const rule = /\.rb-notes \{([^}]*)\}/.exec(HEADER_CSS)?.[1] ?? '';
    expect(rule).toMatch(/position: absolute;[\s\S]*top: 8px;[\s\S]*right: 8px;/);
    expect(rule).toMatch(/width: var\(--rb-notes-w, 440px\);[\s\S]*height: var\(--rb-notes-h, 380px\);/);
    expect(rule).toContain('resize: both;');
    expect(HEADER_CSS).toMatch(/@media \(max-width: 700px\) \{\s*\.rb-notes \{[^}]*bottom: 0;[^}]*resize: none;/);
    expect(document.activeElement).toBe(q('[data-notes-panel] textarea'));
    expect(q('[data-md-hints]')).toBeNull();
    q('[data-md-hint-key]').click();
    flushSync();
    expect(q('[data-md-hints]').textContent).toContain('**bold**');
  });

  it('shows the counter only near the 8000 cap, and the box takes no more', async () => {
    host.value = 'x'.repeat(100);
    await draw();
    expect(q('[data-notes-count]')).toBeNull();
    expect(q<HTMLTextAreaElement>('[data-notes-panel] textarea').maxLength).toBe(MAX_NOTE);
    type('x'.repeat(7600));
    expect(q('[data-notes-count]').textContent).toBe('7,600 of 8,000');
    expect(q('[data-notes-count]').dataset.atCap).toBe('false');
    type('x'.repeat(MAX_NOTE));
    expect(q('[data-notes-count]').dataset.atCap).toBe('true');
  });

  it('frames the text box so the one focus rule lights its hairline, and keeps nothing in the browser itself', async () => {
    await draw();
    const field = q('[data-notes-panel] .oc-notes-field');
    expect(field.classList.contains('oc-focus-host')).toBe(true);
    expect(field.classList.contains('oc-notes-field--framed')).toBe(true);
    type('look at the footer spacing');
    expect(typedSpy).toHaveBeenCalledWith('look at the footer spacing');
    expect(localStorage.length).toBe(0);
  });
});

describe('the payload note kept in this browser (NoteKeeper)', () => {
  it('takes the kept words back once into an empty note after a reload, then mirrors the note as it changes', () => {
    new NoteKeeper().follow(KEY, 'look at the footer spacing');
    expect(readNote(KEY)).toBe('look at the footer spacing');
    const keeper = new NoteKeeper();
    expect(keeper.follow(KEY, '')).toBe('look at the footer spacing');
    expect(keeper.follow(KEY, 'look at the footer spacing')).toBeNull();
    expect(keeper.follow(KEY, 'look at the footer spacing, and the gap')).toBeNull();
    expect(readNote(KEY)).toBe('look at the footer spacing, and the gap');
  });

  it('forgets the words whenever the host empties the note, however it was emptied, so a sent or cleared note never comes back', () => {
    const keeper = new NoteKeeper();
    keeper.follow(KEY, 'already sent');
    expect(keeper.follow(KEY, '')).toBeNull();
    expect(readNote(KEY)).toBe('');
    expect(new NoteKeeper().follow(KEY, '')).toBeNull();
    localStorage.setItem(KEY, 'older words');
    expect(new NoteKeeper().follow(KEY, 'newer words')).toBeNull();
    expect(readNote(KEY)).toBe('newer words');
    expect(new NoteKeeper().follow(noteKey('20261013-bottom-bar', 'r4'), '')).toBeNull();
  });
});
