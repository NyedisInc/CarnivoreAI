/** @vitest-environment jsdom */
import { describe, expect, test, vi } from 'vitest';

const prompt = vi.hoisted(() => vi.fn(async () => null));
vi.mock('../../sidebar-shell/company-actions', () => ({ newCompanyPrompt: prompt }));

describe('companies heading menu', { timeout: 100_000 }, () => {
    test('lists new company... and picking it prompts', async () => {
        await import('./all');
        const { itemMenu } = await import('../registry');
        const built = itemMenu('section', { key: 'companies', anchor: document.createElement('div') }, { close: () => {}, glyph: () => '' });
        const nodes = built!.nodes as unknown as { id: string; label: string; run: () => void }[];
        const node = nodes.find((n) => n.id === 'new-company');
        expect(node?.label).toBe('new company...');
        node!.run();
        expect(prompt).toHaveBeenCalledWith(null);
    });
});
