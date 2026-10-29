import { SETTINGS_SECTIONS, type SectionId } from './settings-registry';
import { tabsOf } from './screen-sections';

export const SECTION_STORAGE_KEY = 'carnivore.settings.section';

export const TAB_STORAGE_KEY = 'carnivore.settings.tabs';

function readSection(): SectionId {
    try {
        const stored = globalThis.localStorage?.getItem(SECTION_STORAGE_KEY);
        const found = SETTINGS_SECTIONS.find((s) => s.id === stored);
        if (found) return found.id;
    } catch {
    }
    return SETTINGS_SECTIONS[0]?.id ?? 'general';
}

function readTabs(): Partial<Record<SectionId, string>> {
    try {
        const raw = globalThis.localStorage?.getItem(TAB_STORAGE_KEY);
        const parsed: unknown = raw ? JSON.parse(raw) : null;
        if (parsed && typeof parsed === 'object') {
            const out: Partial<Record<SectionId, string>> = {};
            for (const section of SETTINGS_SECTIONS) {
                const slug = (parsed as Record<string, unknown>)[section.id];
                if (typeof slug === 'string') out[section.id] = slug;
            }
            return out;
        }
    } catch {
    }
    return {};
}

class SettingsView {
    #section = $state<SectionId>(readSection());
    #tabs = $state<Partial<Record<SectionId, string>>>(readTabs());

    get section(): SectionId {
        return this.#section;
    }

    set section(id: SectionId) {
        this.#section = id;
        try {
            globalThis.localStorage?.setItem(SECTION_STORAGE_KEY, id);
        } catch {
        }
    }

    tabOf(section: SectionId): string | null {
        const slugs = tabsOf(section);
        const stored = this.#tabs[section];
        if (stored !== undefined && slugs.includes(stored)) return stored;
        return slugs[0] ?? null;
    }

    setTab(section: SectionId, slug: string): void {
        if (!tabsOf(section).includes(slug)) return;
        this.#tabs = { ...this.#tabs, [section]: slug };
        try {
            globalThis.localStorage?.setItem(TAB_STORAGE_KEY, JSON.stringify(this.#tabs));
        } catch {
        }
    }
}

export const settingsView = new SettingsView();
