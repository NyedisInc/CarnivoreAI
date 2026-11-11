/** @vitest-environment jsdom */
import { expect, it, vi } from 'vitest';
import { flushSync } from 'svelte';

vi.mock('../../opscenter/api/projects.svelte', () => ({ projects: { data: [{ id: 5, name: 'proj', root: '/a', path: '/a', company_id: null }] } }));
vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
    ...(await original<Record<string, unknown>>()),
    authFetch: async () => ({ machines: [], computers: [], peers: [] }),
}));
vi.mock('./interaction-globals', () => ({
    announce: () => {}, announceFailure: () => {}, hg: () => ({}), reasonOf: String, refetchDrawer: async () => {}, usableGroups: () => null, repaintDrawerRows: () => {},
}));

vi.mock('./company-actions', () => ({ fileProject: () => {}, newCompanyPrompt: () => {}, removeFromCompany: () => {} }));
vi.mock('./heading-project-actions', () => ({
    archiveProject: () => {}, newAgentInProject: () => {}, projectNameFor: () => 'proj', renameProject: () => {}, showProjectPath: () => {}, sleepProject: () => {},
}));

it('choosing move to pack member on a drawer project opens the migrate window', async () => {
    const { runDrawerProjectVerb } = await import('./project-menu-run.svelte');
    runDrawerProjectVerb('p:5', 'migrate-project');
    flushSync();
    await Promise.resolve();
    flushSync();
    expect(document.querySelectorAll('[data-migrate-wizard]').length, 'one wizard').toBe(1);
    expect(document.querySelector('.modal-overlay [data-migrate-wizard]'), 'drawn inside a centered overlay').not.toBeNull();
    const { closeMigrate } = await import('../pack-migrate/migrate-store.svelte');
    closeMigrate();
    flushSync();
    const page = document.body.appendChild(document.createElement('div'));
    page.className = 'sp-body';
    runDrawerProjectVerb('p:5', 'migrate-project');
    flushSync();
    expect(document.querySelector('.modal-overlay [data-migrate-wizard]'), 'no second wizard while the page is open').toBeNull();
}, 60000);
