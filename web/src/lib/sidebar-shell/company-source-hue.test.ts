/** @vitest-environment jsdom */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync } from 'svelte';

const mockState = vi.hoisted(() => ({
    rows: [] as Array<{ id: number; name: string; parent_id?: number | null; hue?: number | null }>,
    repaint: vi.fn(),
}));

vi.mock('../companies/api', () => ({
    listCompanies: async () => structuredClone(mockState.rows),
}));

vi.mock('../../opscenter/api/projects.svelte', () => ({
    projects: { data: [] },
}));

vi.mock('./interaction-globals', () => ({
    repaintDrawerRows: () => mockState.repaint(),
}));

vi.mock('../drawer/archived-visibility', () => ({
    archivedProjects: () => [],
    archivedShown: () => false,
}));

import { auth } from '../../opscenter/api/auth.svelte';
import { companies } from '../companies';
import { watchCompanies } from './company-source.svelte';

describe('watchCompanies company hue repaint', () => {
    beforeEach(() => {
        auth.state = 'signed-in';
        mockState.repaint.mockClear();
        mockState.rows = [{ id: 1, name: 'Acme', parent_id: null, hue: 120 }];
    });

    it('repaints the drawer when only company hue changes or clears, and skips identical refreshes', async () => {
        await companies.refresh();
        watchCompanies();
        flushSync();
        expect(mockState.repaint).toHaveBeenCalledTimes(0);

        await companies.refresh();
        flushSync();
        expect(mockState.repaint).toHaveBeenCalledTimes(0);

        mockState.rows = [{ id: 1, name: 'Acme', parent_id: null, hue: 260 }];
        await companies.refresh();
        flushSync();
        expect(mockState.repaint).toHaveBeenCalledTimes(1);

        mockState.rows = [{ id: 1, name: 'Acme', parent_id: null, hue: null }];
        await companies.refresh();
        flushSync();
        expect(mockState.repaint).toHaveBeenCalledTimes(2);
    });
});
