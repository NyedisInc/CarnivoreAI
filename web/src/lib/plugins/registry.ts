import type { Contribution, Plugin, PluginContext, PluginSurface } from './types';

export const NO_CONTEXT: PluginContext = { flags: {}, refresh: () => undefined };

export interface PluginRegistry {
    register(plugin: Plugin): boolean;
    surfacesOf<K extends PluginSurface>(kind: K): readonly Contribution<K>[];
}

function byOrderThenId(a: Contribution, b: Contribution): number {
    const ao = a.order ?? 0;
    const bo = b.order ?? 0;
    if (ao !== bo) return ao - bo;
    if (a.id === b.id) return 0;
    return a.id < b.id ? -1 : 1;
}

export function createRegistry(): PluginRegistry {
    const pluginIds = new Set<string>();
    const bySurface = new Map<PluginSurface, Contribution[]>();

    function idTaken(c: Contribution): boolean {
        const held = bySurface.get(c.surface);
        return !!held && held.some((existing) => existing.id === c.id);
    }

    function register(plugin: Plugin): boolean {
        if (!plugin || typeof plugin.id !== 'string' || !plugin.id) {
            console.error('[plugins] refused a plugin with no id');
            return false;
        }
        if (pluginIds.has(plugin.id)) {
            console.error(
                `[plugins] refused duplicate plugin id "${plugin.id}" - the `
                + 'one already registered is kept');
            return false;
        }
        const incoming = plugin.contributions || [];
        const seen = new Set<string>();
        for (const c of incoming) {
            if (!c || typeof c.id !== 'string' || !c.id) {
                console.error(
                    `[plugins] refused plugin "${plugin.id}": a contribution `
                    + 'has no id');
                return false;
            }
            const key = `${c.surface}\0${c.id}`;
            if (seen.has(key) || idTaken(c)) {
                console.error(
                    `[plugins] refused plugin "${plugin.id}": contribution id `
                    + `"${c.id}" is already registered on surface `
                    + `"${c.surface}" - the one already registered is kept`);
                return false;
            }
            seen.add(key);
        }
        pluginIds.add(plugin.id);
        for (const c of incoming) {
            const held = bySurface.get(c.surface);
            if (held) held.push(c);
            else bySurface.set(c.surface, [c]);
        }
        return true;
    }

    function surfacesOf<K extends PluginSurface>(kind: K): readonly Contribution<K>[] {
        const held = bySurface.get(kind);
        if (!held) return [];
        return [...held].sort(byOrderThenId) as Contribution<K>[];
    }

    return { register, surfacesOf };
}

const registry = createRegistry();

export function register(plugin: Plugin): boolean {
    return registry.register(plugin);
}

export function surfacesOf<K extends PluginSurface>(kind: K): readonly Contribution<K>[] {
    return registry.surfacesOf(kind);
}
