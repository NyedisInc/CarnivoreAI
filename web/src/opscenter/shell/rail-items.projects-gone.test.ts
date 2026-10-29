import { describe, expect, it } from 'vitest';
import { RAIL_DESTINATIONS, RAIL_RUN } from './rail-items';
import { RAIL_HINT_ROWS } from './rail-hints';
import { MENU_PAGES } from '../../lib/menu-page/menu-pages';
import catalog from '../../../../client/js/i18n/catalog.en.js';

describe('the projects page is removed', () => {
    it('has no projects row, run, hint or menu page', () => {
        expect(RAIL_DESTINATIONS.some((r) => r.id === 'projects')).toBe(false);
        expect(RAIL_RUN.projects).toBeUndefined();
        expect(RAIL_HINT_ROWS.some((r) => r.id === 'projects')).toBe(false);
        expect(MENU_PAGES.some((p) => p.id === 'projects' || p.containerId === 'projects-screen')).toBe(false);
    });

    it('shows the sessions row as "projects" with the folder icon', () => {
        const row = RAIL_DESTINATIONS.find((r) => r.id === 'sessions');
        expect(row?.icon).toBe('folder');
        expect((catalog as Record<string, string>)[row!.labelKey]).toBe('projects');
    });

    it('lands the old #projects routes on the sessions page', () => {
        const page = MENU_PAGES.find((p) => p.id === 'sessions');
        expect(page?.hashes).toContain('#projects');
    });
});
