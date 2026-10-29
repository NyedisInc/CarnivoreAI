import type { ReportGate } from '../catalog/publish';
import { displayKind, isCplugIndexKind } from '../catalog/kind-display';

export type KindTab = 'skills' | 'themes' | 'mods' | 'plugins';

export interface KindedLocation {
    kind?: string | null;
}

const KIND_PLUGIN = 'plugin';

const TAB_OF_KIND: Record<string, KindTab> = {
    skill: 'skills',
    theme: 'themes',
    mod: 'mods',
    [KIND_PLUGIN]: 'plugins',
};

const WORD_OF_TAB: Record<KindTab, string> = {
    skills: 'skill',
    themes: 'theme',
    mods: 'mod',
    plugins: 'plugin',
};

export function tabOf(kind: string | null | undefined): KindTab | null {
    return TAB_OF_KIND[displayKind(kind ?? 'skill') ?? 'skill'] ?? null;
}

export function realKind(location: KindedLocation): string {
    return location.kind || 'skill';
}

export function kindWord(kind: string | null | undefined): string {
    return `skill.publish.kind.${WORD_OF_TAB[tabOf(kind) ?? 'skills']}`;
}

export function folderPhrase(tab: KindTab): string {
    return `publish.page.folder.${WORD_OF_TAB[tab]}`;
}

export function foundByFact(location: KindedLocation): { label: string; value: string } | null {
    if (tabOf(location.kind) !== 'plugins') return null;
    return { label: 'publish.page.fact.found_by', value: 'publish.page.fact.found_by_value' };
}

export function cleanRoomSkipExpected(location: KindedLocation): boolean {
    return isCplugIndexKind(location.kind);
}

export function cleanRoomSkipped(report: { gates?: Pick<ReportGate, 'id' | 'verdict' | 'code'>[] } | null | undefined): boolean {
    return (report?.gates ?? []).some(
        (gate) => gate.id === 'clean_room' && gate.verdict === 'advisory' && gate.code === 'skipped_by_policy',
    );
}

export function emptyKey(tab: KindTab): string {
    return tab === 'plugins' ? 'skill.publish.kind.none_plugin' : 'skill.publish.kind.none';
}
