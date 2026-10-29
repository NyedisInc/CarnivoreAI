/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import { ListingStore } from '../listing-push/store';
import type { RowHost } from '../sidebar-shell/row-host';
import { buildRowPlan } from '../sidebar-shell/row-plan';
import SessionRow from '../sidebar-shell/SessionRow.svelte';
import { mergeLiveRow, type DrawerRow, type LiveInfo } from './fetch';

describe('mergeLiveRow carries the Task Manager roles', () => {
    let container: HTMLElement;
    let component: unknown;

    afterEach(() => {
        if (component) unmount(component as never);
        container?.remove();
    });

    function provider(row: DrawerRow): Element {
        container = document.body.appendChild(document.createElement('div'));
        component = mount(SessionRow, { target: container, props: { p: buildRowPlan(row as never, 'compact', undefined, null, {} as RowHost) as never } });
        flushSync();
        return container.querySelector('.session-sidebar-row-provider')!;
    }

    const live = (over: Record<string, unknown>): LiveInfo => ({ tmux_session: 'cloude_a', agent_family: 'claude', ...over }) as LiveInfo;

    it('a built row and an existing row draw the one role mark: the star on a lead, nothing for do not disturb', () => {
        const built: DrawerRow[] = [];
        mergeLiveRow(built, live({ task_lead: true, do_not_disturb: true }));
        const lead = provider(built[0]!);
        expect(lead.querySelector('.session-sidebar-row-provider__lead svg')).not.toBeNull();
        expect(lead.querySelector('.session-sidebar-row-provider__dnd')).toBeNull();
        expect(lead.getAttribute('data-dnd')).toBeNull();
        unmount(component as never); component = null; container.remove();
        const existing: DrawerRow[] = [{ name: 'cloude_a', agent_family: 'claude' }];
        mergeLiveRow(existing, live({ task_lead: false, do_not_disturb: true }));
        const dnd = provider(existing[0]!);
        expect(dnd.querySelector('.session-sidebar-row-provider__dnd')).toBeNull();
        expect(dnd.querySelector('.session-sidebar-row-provider__lead')).toBeNull();
        expect(dnd.getAttribute('data-dnd')).toBeNull();
        expect(dnd.getAttribute('data-role-lead')).toBeNull();
    });

    it('overwrite-only: false, null and absent draw nothing and never keep a stale true', () => {
        const rows: DrawerRow[] = [{ name: 'cloude_a', agent_family: 'claude', task_lead: true, do_not_disturb: true }];
        mergeLiveRow(rows, live({ task_lead: false, do_not_disturb: null }));
        expect(rows[0]!.task_lead).toBe(false);
        expect(rows[0]!.do_not_disturb).toBeNull();
        mergeLiveRow(rows, live({}));
        expect(rows[0]!.task_lead).toBeNull();
        const p = provider(rows[0]!);
        expect(p.querySelector('.session-sidebar-row-provider__lead')).toBeNull();
        expect(p.querySelector('.session-sidebar-row-provider__dnd')).toBeNull();
    });

    it('a listing.delta that flips the roles reaches the row', async () => {
        const store = new ListingStore({
            fetchSnapshot: async () => ({ stream: 's', seq: 1, collections: { list: { ok: true, status: null, detail: null, meta: {},
                rows: [{ tmux_session: 'cloude_a', agent_family: 'claude', task_lead: false, do_not_disturb: null, session: { id: 'ses_a' } }] } } }),
            setTimer: () => 0,
        });
        await store.hello();
        const draw = (): Element => {
            const rows: DrawerRow[] = [];
            for (const info of store.rows<LiveInfo>('list')!) mergeLiveRow(rows, info);
            return provider(rows[0]!);
        };
        store.frame({ type: 'listing.delta', stream: 's', seq: 2, changes: { list: { upsert: [{ key: 'ses_a', fields: { do_not_disturb: true } }] } } });
        let p = draw();
        expect(p.querySelector('.session-sidebar-row-provider__dnd')).toBeNull();
        expect(p.querySelector('.session-sidebar-row-provider__lead')).toBeNull();
        unmount(component as never); component = null; container.remove();
        store.frame({ type: 'listing.delta', stream: 's', seq: 3, changes: { list: { upsert: [{ key: 'ses_a', fields: { task_lead: true, do_not_disturb: false } }] } } });
        p = draw();
        expect(p.querySelector('.session-sidebar-row-provider__lead')).not.toBeNull();
        expect(p.querySelector('.session-sidebar-row-provider__dnd')).toBeNull();
    });
});
