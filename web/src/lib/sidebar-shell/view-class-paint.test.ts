/** @vitest-environment jsdom */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { drawList, loadLegacyDrawer, resetDrawer } from './legacy-fixture';
import * as Store from '../drawer/store';
import { setViewClassSource } from '../drawer/view-class';

vi.mock('./company-source.svelte', () => ({
    companySource: () => ({ companies: [{ id: 7, name: 'acme' }], companyOf: (id: string) => (String(id) === '1' ? 7 : null) }),
    watchCompanies: () => {},
}));

const rows = [
    { name: 'cloude_a', created_by_cloude: true, status: 'working', unread: false, is_pinned: true, project_id: 1, project_name: 'one' },
    { name: 'cloude_b', created_by_cloude: true, status: 'idle', unread: false, is_pinned: false, project_id: 1, project_name: 'one' },
];

beforeAll(() => { loadLegacyDrawer(); });
beforeEach(() => { resetDrawer(); });
afterEach(() => { setViewClassSource(null); });

describe('the list paints from its device class fold list', () => {
    it('a band folded only in the phone list is drawn folded on a phone and open on a desktop', () => {
        Store.save(['cloude_a'], rows.map((r) => r.name), [], undefined, undefined, ['companies']);
        const draw = (): HTMLElement => {
            drawList(rows);
            return document.getElementById('session-sidebar-list')!;
        };
        setViewClassSource(() => 'mobile');
        const phone = draw();
        expect(phone.querySelector('.session-sidebar-companies [aria-expanded="false"]')).toBeTruthy();
        expect(phone.querySelector('.session-sidebar-company')).toBeNull();
        setViewClassSource(() => 'desktop');
        const desktop = draw();
        expect(desktop.querySelector('.session-sidebar-companies [aria-expanded="true"]')).toBeTruthy();
        expect(desktop.querySelector('.session-sidebar-company')).toBeTruthy();
    });
});
