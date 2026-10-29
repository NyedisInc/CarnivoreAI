import { SETTINGS_SECTIONS, groupsIn, slugOf, type ScreenKind, type SectionId } from './settings-registry';

export const SCREEN_TABS: Readonly<Record<ScreenKind, readonly string[]>> = {
    'launch-profiles': [],
    keys: [],
    desktop: [],
};

export function tabsOf(section: SectionId): readonly string[] {
    const screen = SETTINGS_SECTIONS.find((s) => s.id === section)?.screen;
    if (screen) return SCREEN_TABS[screen];
    return groupsIn(section).map(slugOf);
}
