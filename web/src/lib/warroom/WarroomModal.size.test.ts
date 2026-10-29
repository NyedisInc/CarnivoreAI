/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import WarroomModal from './WarroomModal.svelte';
import { WAR_ROOM_H, WAR_ROOM_W } from './modal-size';

vi.mock('../../opscenter/cells/terminal-live/Cell.svelte', async () => ({ default: (await import('../zone-shell/fixtures/TerminalHostStub.svelte')).default }));
vi.mock('../../opscenter/shell/WidgetHead.svelte', async () => ({ default: (await import('../zone-shell/fixtures/CornerStub.svelte')).default }));
vi.mock('../../opscenter/api', () => ({ sessions: { data: [] } }));
vi.mock('../../opscenter/api/host', () => ({ openSession: () => {} }));
vi.mock('../../opscenter/layouts/page.svelte', () => ({ openLayout: async () => {} }));
vi.mock('../layouts-bridge/api.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../layouts-bridge/api.svelte')>()),
  layouts: { get data() { return []; }, refresh: async () => {} },
}));

vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });

let app: ReturnType<typeof mount> | null = null;

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('the war room modal panel', () => {
  test('is sized 1100 by 760 (clamped to the viewport) by ModalShell, and the terminal host fills the body', () => {
    const info = { session: { id: 'ses_7' }, session_row_id: 7, tmux_session: 'carnivore_x', label: 'seven' };
    app = mount(WarroomModal, { target: document.body.appendChild(document.createElement('div')), props: { info: info as never, close: () => {} } });
    flushSync();
    const panel = document.querySelector<HTMLElement>('.modal-overlay .modal-content')!;
    expect([WAR_ROOM_W, WAR_ROOM_H]).toEqual(['min(1100px, 94vw)', 'min(760px, 88vh)']);
    expect(panel.style.maxWidth).toBe('none');
    expect(panel.classList.contains('modal-content--fill')).toBe(true);
    const host = panel.querySelector<HTMLElement>('[data-terminal-host]')!;
    expect(host.parentElement?.classList.contains('wrm-body')).toBe(true);
    expect(host.parentElement?.parentElement?.classList.contains('modal-body')).toBe(true);
  });
});
