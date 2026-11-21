/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import { cplugEnablement } from '../host/enablement.svelte';
import { registerBoardAttachments, resetBoardAttachments, unregisterBoardAttachments } from '../sdk/board-attachments';
import { registerRoundOpener, resetRoundOpener } from '../sdk/round-opener';
import { typeKey } from './board-card-model';
import TaskManagerBoardCard from './TaskManagerBoardCard.svelte';

const stop = vi.fn();
vi.mock('../../lib/resource-push/boot', () => ({
  resourcePush: () => ({ pushOrPoll: () => stop, onChange: () => () => undefined, isLive: () => true }),
}));

const board = { slug: '20261013-bottom-bar', revision: 'r2', title: 'bottom bar', summary: 'the bar now sits at the bottom' };
const files = [
  { file_id: 'aaaaaaaa', name: 'spec.pdf', revision: 'r2', removed: false },
  { file_id: 'dddddddd', name: 'brief.docx', revision: 'r2', removed: false },
  { file_id: 'bbbbbbbb', name: 'old.png', revision: 'r2', removed: true },
  { file_id: 'cccccccc', name: 'other-rev.md', revision: 'r1', removed: false },
];
const TOPIC = 'cplug.reviewboard.boards';

let app: ReturnType<typeof mount> | null = null;
const settle = async (): Promise<void> => { await new Promise((r) => setTimeout(r, 0)); flushSync(); };
const row = (id: string): Element => document.querySelector(`[data-task-manager-board-file="${id}"]`)!;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  resetBoardAttachments();
  resetRoundOpener();
  vi.clearAllMocks();
});

describe('the board card', () => {
  it('draws the title, the summary, the live count and every file of this revision with its type word, a removed one tagged', async () => {
    registerBoardAttachments({ read: async () => files, topic: TOPIC });
    app = mount(TaskManagerBoardCard, { target: document.body, props: { board } });
    await settle();
    const card = document.querySelector('[data-task-manager-board="20261013-bottom-bar"]')!;
    expect(card.textContent).toContain('bottom bar');
    expect(card.querySelector('[data-task-manager-board-summary]')!.textContent).toBe('the bar now sits at the bottom');
    expect(card.querySelector('[data-task-manager-board-count]')!.textContent).toContain('(2)');
    expect(row('aaaaaaaa').querySelector('.hdbc-type')!.textContent).toBe('pdf');
    expect(row('dddddddd').querySelector('.hdbc-type')!.textContent).toBe('document');
    expect(row('bbbbbbbb').textContent).toContain('removed');
    expect(row('aaaaaaaa').textContent).not.toContain('removed');
    expect(card.textContent).not.toContain('other-rev.md');
  });

  it('clears the list when the board plugin goes off', async () => {
    let on = true;
    registerBoardAttachments({ read: async () => files, topic: TOPIC }, () => on);
    app = mount(TaskManagerBoardCard, { target: document.body, props: { board } });
    await settle();
    expect(row('aaaaaaaa')).not.toBeNull();
    on = false;
    unmount(app);
    app = mount(TaskManagerBoardCard, { target: document.body, props: { board } });
    await settle();
    expect(document.querySelector('[data-task-manager-board-file]')).toBeNull();
  });

  it('opens the board with the opener as it is at the press', async () => {
    const opener = vi.fn(async () => undefined);
    registerBoardAttachments({ read: async () => files, topic: TOPIC });
    registerRoundOpener(opener);
    app = mount(TaskManagerBoardCard, { target: document.body, props: { board } });
    await settle();
    resetRoundOpener();
    const later = vi.fn(async () => undefined);
    registerRoundOpener(later);
    (document.querySelector('[data-task-manager-board-open]') as HTMLButtonElement).click();
    expect(later).toHaveBeenCalledWith({ slug: '20261013-bottom-bar', revision: 'r2' });
    expect(opener).not.toHaveBeenCalled();
  });

  it('shows the open button once an opener registers after the card is drawn, and hides it after a reset, with no remount', async () => {
    app = mount(TaskManagerBoardCard, { target: document.body, props: { board } });
    await settle();
    expect(document.querySelector('[data-task-manager-board-open]')).toBeNull();
    registerRoundOpener(async () => undefined);
    await settle();
    expect(document.querySelector('[data-task-manager-board-open]')).not.toBeNull();
    resetRoundOpener();
    await settle();
    expect(document.querySelector('[data-task-manager-board-open]')).toBeNull();
  });

  it('is the title and summary alone while no plugin registered a source', async () => {
    app = mount(TaskManagerBoardCard, { target: document.body, props: { board } });
    await settle();
    expect(document.querySelector('[data-task-manager-board-count]')).toBeNull();
    expect(document.body.textContent).toContain('the bar now sits at the bottom');
  });

  it('stops its subscription when the card unmounts', async () => {
    registerBoardAttachments({ read: async () => files, topic: TOPIC });
    app = mount(TaskManagerBoardCard, { target: document.body, props: { board } });
    await settle();
    expect(stop).not.toHaveBeenCalled();
    unmount(app);
    app = null;
    expect(stop).toHaveBeenCalledTimes(1);
  });
});

describe('the board card follows its plugin', () => {
  const two = [{ file_id: 'a1a1a1a1', name: 'a.pdf', revision: 'r1', removed: false }, { file_id: 'b2b2b2b2', name: 'b.pdf', revision: 'r2', removed: false }];

  it('shows nothing on two cards of one board once the plugin is switched off, with no push frame sent', async () => {
    cplugEnablement.enabled = { reviewboard: true };
    registerBoardAttachments({ read: async () => two, topic: TOPIC }, () => cplugEnablement.enabled['reviewboard'] === true);
    const one = mount(TaskManagerBoardCard, { target: document.body, props: { board: { ...board, revision: 'r1' } } });
    const other = mount(TaskManagerBoardCard, { target: document.body, props: { board: { ...board, revision: 'r2' } } });
    await settle();
    expect(document.querySelectorAll('[data-task-manager-board-file]')).toHaveLength(2);
    cplugEnablement.enabled = { reviewboard: false };
    unregisterBoardAttachments();
    await settle();
    expect(document.querySelectorAll('[data-task-manager-board-file]')).toHaveLength(0);
    unmount(one);
    unmount(other);
  });

  it('a card drawn before the plugin registers shows its files once it does', async () => {
    app = mount(TaskManagerBoardCard, { target: document.body, props: { board: { ...board, revision: 'r1' } } });
    await settle();
    expect(document.querySelector('[data-task-manager-board-file]')).toBeNull();
    registerBoardAttachments({ read: async () => two, topic: TOPIC });
    await settle();
    expect(document.querySelector('[data-task-manager-board-file="a1a1a1a1"]')).not.toBeNull();
  });
});

describe('the type word', () => {
  it('comes from the extension, case blind, and falls back to file', () => {
    expect(typeKey('Spec.DOCX')).toBe('cplug.huddle.board.type.document');
    expect(typeKey('logo.svg')).toBe('cplug.huddle.board.type.svg');
    expect(typeKey('README')).toBe('cplug.huddle.board.type.file');
    expect(typeKey('a.exe')).toBe('cplug.huddle.board.type.file');
  });
});
