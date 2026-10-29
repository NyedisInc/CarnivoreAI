import type { Inventory, SkillLocationRow } from './skills-types';

export interface Seen {
    readonly method: string;
    readonly path: string;
    readonly body: Record<string, unknown> | null;
}

export function loc(over: Partial<SkillLocationRow> & Pick<SkillLocationRow, 'name'>): SkillLocationRow {
    const harness = over.harness ?? 'claude';
    return {
        location_id: `${over.scope ?? 'personal'}-${harness}:${over.name}`,
        root_key: `${over.scope ?? 'personal'}-${harness}`,
        folder: over.name,
        harness,
        scope: 'personal',
        path: `/home/x/.claude/skills/${over.name}`,
        description: `does ${over.name} things`,
        description_tokens_est: 40,
        is_symlink: false,
        link_target: null,
        read_only: false,
        plugin: null,
        project_path: null,
        toggle:
            harness === 'codex'
                ? { kind: 'on_off', states: ['on', 'off'], reason: 'codex can only switch a skill on or off' }
                : { kind: 'four_state', states: ['on', 'name-only', 'user-invocable-only', 'off'], reason: null },
        state: 'on',
        state_source: null,
        managed: null,
        shadowed_by: null,
        shadows: [],
        ...over,
    };
}

export function fixtureInventory(): Inventory {
    const sme = loc({
        name: 'sme',
        description: 'expert on everything '.repeat(30),
        description_tokens_est: 150,
        managed: { source: 'ledger', item_id: 'acme/sme', version: '1.2.0', update_available: false },
        extends: 'huddle',
        guide_rev: 2,
        behind_rules: { written_for: 2, current: 3, changes: [{ rev: 3, summary: 'add-ons declare guide_rev' }] },
    });
    const progressClaude = loc({ name: 'progress' });
    const progressCodex = loc({ name: 'progress', harness: 'codex', path: '/home/x/.agents/skills/progress' });
    const plugin = loc({
        name: 'pluginskill',
        scope: 'plugin',
        plugin: 'acme',
        read_only: true,
        toggle: { kind: 'none', states: [], reason: 'plugin skills switch with the whole plugin' },
    });
    const dupPersonal = loc({ name: 'dup', shadows: ['project-claude:dup'] });
    const dupProject = loc({
        name: 'dup',
        scope: 'project',
        project_path: '/work/lab',
        shadowed_by: 'personal-claude:dup',
    });
    const noisy = loc({ name: 'noisy', state: 'off', state_source: 'user' });
    return {
        context: { profile: 'default', group_id: 'cg-1', project_path: null },
        profile_groups: [
            { group_id: 'cg-1', profiles: ['default', 'work'], own_folder: false, exists: true },
            { group_id: 'cg-2', profiles: ['claude-code-bench'], own_folder: true, exists: true },
        ],
        skills: [
            { name: 'dup', locations: [dupPersonal, dupProject] },
            { name: 'noisy', locations: [noisy] },
            { name: 'pluginskill', locations: [plugin] },
            { name: 'progress', locations: [progressClaude, progressCodex] },
            { name: 'sme', locations: [sme] },
        ],
        settings_unparseable: [],
        tokens_label: 'est.',
    };
}

export function fakeServer(inventory: Inventory = fixtureInventory()) {
    const seen: Seen[] = [];
    const fetcher = (async (path: string, init: RequestInit = {}) => {
        const method = init.method ?? 'GET';
        const body = init.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
        seen.push({ method, path, body });
        if (path === '/projects') {
            return [
                { name: 'lab', path: '/work/lab', root: '/work/lab', archived_at: null },
                { name: 'old', path: '/work/old', root: '/work/old', archived_at: '2026-01-01' },
            ];
        }
        if (path === '/catalog/installed') {
            return {
                items: [
                    {
                        install_id: 'inst-sme',
                        item_id: 'acme/sme',
                        name: 'sme',
                        version: '1.2.0',
                        scope: 'global',
                        revision: 3,
                        consent_via: 'one_click',
                        auto_update: true,
                        update_available: false,
                        forked: false,
                        drift: { state: 'drifted', changed_files: ['SKILL.md'], checked_at: 1 },
                    },
                ],
            };
        }
        if (path.startsWith('/skill-fires/usage')) {
            return path.endsWith('=sme')
                ? { skill: 'sme', state: 'measured', fired_7d: 1, fired_30d: 4, fired_90d: 9 }
                : { skill: 'x', state: 'not_measured' };
        }
        if (path.startsWith('/skills/') && path.includes('/autopsy')) {
            return path.startsWith('/skills/sme/')
                ? {
                      skill: 'sme', days: 30, state: 'measured', fires: 4, spans_measured: 4, tool_calls: 12, tool_errors: 1,
                      interrupts: 0, corrections: 0, corrections_measured: 4, tokens_total: 900, categories: { network: 2 },
                      undisclosed: ['network'], recent: [],
                  }
                : { skill: 'x', days: 30, state: 'not_measured' };
        }
        if (path.startsWith('/catalog/items/')) {
            return {
                item: {
                    id: 'acme/sme', name: 'sme', latest: '1.2.0', cost: { desc_tokens: 150, body_tokens: 900 },
                    versions: [{ v: '1.2.0', digest: 'abcdef0123456789', scripts: 0, sig: { key_id: 'acme' }, review: { status: 'reviewed', verdict: 'clean', warnings: [] } }],
                },
            };
        }
        if (path.startsWith('/catalog/contents/')) throw new Error('not read until asked');
        if (path.startsWith('/skills/census')) {
            return {
                state: 'measured',
                tokens_label: 'est.',
                skills: [
                    { name: 'sme', harnesses: ['claude'], scopes: ['personal'], locations: 1, states: { claude: 'on' }, tokens_est: 150, fires: { d7: 1, d30: 4, d90: 9 } },
                    { name: 'noisy', harnesses: ['claude'], scopes: ['personal'], locations: 1, states: { claude: 'off' }, tokens_est: 40, fires: { d7: 0, d30: 0, d90: 0 } },
                    { name: 'blind', harnesses: ['codex'], scopes: ['project'], locations: 1, states: { codex: 'on' }, tokens_est: 20, fires: null },
                ],
            };
        }
        if (path.startsWith('/skills?') || path === '/skills') return inventory;
        if (path === '/skills/overrides' && body) {
            const name = String(body['skill']);
            const state = (body['state'] as string | null) ?? 'on';
            for (const group of inventory.skills) {
                if (group.name !== name) continue;
                (group as unknown as { locations: SkillLocationRow[] }).locations = group.locations.map((l) =>
                    l.harness === body['harness'] ? { ...l, state, state_source: body['state'] === null ? null : String(body['file']) } : l,
                );
            }
            return {
                harness: body['harness'],
                file: body['file'],
                skill: name,
                state: body['state'],
                wrote: true,
                restart_required: body['harness'] === 'codex',
                reload_hint: null,
            };
        }
        if (path.startsWith('/skills/locations/') && method === 'DELETE') return { name: 'x', trashed_to: '/t' };
        throw new Error(`unexpected ${method} ${path}`);
    }) as never;
    return { fetcher, seen, inventory };
}
