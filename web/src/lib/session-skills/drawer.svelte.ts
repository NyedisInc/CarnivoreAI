const STORAGE_KEY = 'cloude.session-skills-drawer.v1';

function load(): Record<string, boolean> {
    try {
        const raw = globalThis.localStorage?.getItem(STORAGE_KEY);
        const parsed: unknown = raw ? JSON.parse(raw) : null;
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
        const out: Record<string, boolean> = {};
        for (const [slot, on] of Object.entries(parsed as Record<string, unknown>)) if (on === true) out[slot] = true;
        return out;
    } catch {
        return {};
    }
}

function save(open: Record<string, boolean>): void {
    try {
        globalThis.localStorage?.setItem(STORAGE_KEY, JSON.stringify(open));
    } catch {
    }
}

const state = $state<{ open: Record<string, boolean> }>({ open: load() });
let focusSlot: string | null = null;

export function skillsDrawerOpen(slot: string): boolean {
    return state.open[slot] === true;
}

export function setSkillsDrawer(slot: string, on: boolean, focus = false): void {
    if (on === (state.open[slot] === true)) return;
    const next = { ...state.open };
    if (on) next[slot] = true;
    else delete next[slot];
    state.open = next;
    focusSlot = on && focus ? slot : null;
    save(next);
}

export function toggleSkillsDrawer(slot: string): boolean {
    setSkillsDrawer(slot, !skillsDrawerOpen(slot), true);
    return skillsDrawerOpen(slot);
}

export function takeDrawerFocus(slot: string): boolean {
    if (focusSlot !== slot) return false;
    focusSlot = null;
    return true;
}
