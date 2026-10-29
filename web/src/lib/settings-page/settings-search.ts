import type { Translate } from '../sessions/types';
import type { PluginEntry } from './plugin-settings/plugin-entries';
import { SETTINGS, SETTINGS_SECTIONS, sectionKey, settingKey, type SectionId, type SettingDef } from './settings-registry';

export interface SettingMatch {
    readonly setting: SettingDef;
    readonly score: number;
}

function parts(text: string): string[] {
    return text.toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(Boolean);
}

function starts(list: readonly string[], word: string): boolean {
    return list.some((part) => part.startsWith(word));
}

interface Haystack {
    readonly label: string[];
    readonly keywords: string[];
    readonly prose: string[];
}

function scoreWord(word: string, hay: Haystack): number {
    if (starts(hay.label, word)) return 8;
    if (starts(hay.keywords, word)) return 4;
    if (starts(hay.prose, word)) return 2;
    if (hay.label.some((part) => part.includes(word))) return 1;
    return 0;
}

export function searchSettings(query: string, t: Translate, settings: readonly SettingDef[] = SETTINGS): SettingMatch[] {
    const wanted = parts(query);
    if (!wanted.length) return [];
    const matches: SettingMatch[] = [];
    for (const setting of settings) {
        const hay: Haystack = {
            label: parts(t(settingKey(setting.id, 'label'))),
            keywords: parts(t(settingKey(setting.id, 'keywords'))),
            prose: [...parts(t(settingKey(setting.id, 'help'))), ...parts(t(sectionKey(setting.section, 'label')))],
        };
        let score = 0;
        let all = true;
        for (const word of wanted) {
            const s = scoreWord(word, hay);
            if (!s) {
                all = false;
                break;
            }
            score += s;
        }
        if (all) matches.push({ setting, score });
    }
    return matches.sort((a, b) => b.score - a.score);
}

export function searchScreenSections(query: string, t: Translate): SectionId[] {
    const wanted = parts(query);
    if (!wanted.length) return [];
    return SETTINGS_SECTIONS.filter((section) => {
        if (!section.screen) return false;
        const hay = [
            ...parts(t(sectionKey(section.id, 'label'))),
            ...parts(t(sectionKey(section.id, 'hint'))),
            ...parts(t(`settings.section.${section.id}.keywords`)),
        ];
        return wanted.every((word) => starts(hay, word));
    }).map((section) => section.id);
}

export interface PluginMatch {
    readonly entry: PluginEntry;
    readonly anchor: string | null;
    readonly label: string;
    readonly help: string;
    readonly score: number;
}

function scoreAll(wanted: readonly string[], hay: Haystack): number {
    let score = 0;
    for (const word of wanted) {
        const s = scoreWord(word, hay);
        if (!s) return 0;
        score += s;
    }
    return score;
}

export function searchPluginSettings(query: string, t: Translate, entries: readonly PluginEntry[]): PluginMatch[] {
    const wanted = parts(query);
    if (!wanted.length) return [];
    const matches: PluginMatch[] = [];
    for (const entry of entries) {
        const name = parts(entry.name);
        const whole = scoreAll(wanted, { label: name, keywords: [], prose: [] });
        if (whole) matches.push({ entry, anchor: null, label: entry.name, help: '', score: whole });
        const schema = entry.item.settingsSchema;
        if (!schema) continue;
        const add = (anchor: string | null, labelKey: string, hintKey?: string, keywordsKey?: string): void => {
            const help = hintKey ? t(hintKey) : '';
            const hay: Haystack = {
                label: parts(t(labelKey)),
                keywords: keywordsKey ? parts(t(keywordsKey)) : [],
                prose: [...parts(help), ...name],
            };
            const score = scoreAll(wanted, hay);
            if (score) matches.push({ entry, anchor, label: t(labelKey), help, score });
        };
        for (const [key, field] of Object.entries(schema.fields)) add(key, field.labelKey, field.hintKey, field.keywordsKey);
        for (const group of schema.groups ?? []) {
            for (const row of group.matrix?.rows ?? []) add(row.fields?.[0] ?? null, row.labelKey, row.hintKey);
        }
    }
    return matches.sort((a, b) => b.score - a.score);
}
