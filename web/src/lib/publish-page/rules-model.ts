/* the limits line */
import type { Translate } from '../sessions/types';
import { dateText, toDate } from './format';
import { folderPhrase, tabOf, type KindTab } from './kinds';
import { dayCap } from './wizard-model';
import type { Limits, Rules } from './types';

/* the empty page */
export const KIND_TABS: readonly KindTab[] = ['skills', 'themes', 'mods', 'plugins'];

export const KIND_WORD: Record<KindTab, string> = { skills: 'skill', themes: 'theme', mods: 'mod', plugins: 'plugin' };

export interface KindRow {
    tab: KindTab;
    word: string;
    open: boolean;
    text: string;
}

export function limitsLine(limits: Limits, t: Translate): string {
    const { per_day, used_today, open_max, open_now } = limits;
    if (per_day === null || used_today === null || open_max === null || open_now === null) return '';
    const base = { today: used_today, per_day, open: open_now, open_max };
    if (limits.new_account && limits.new_account_per_day !== null && limits.new_account_days !== null) {
        return t('publish.new.limits', { ...base, per_day: dayCap(limits) ?? per_day, new_account_per_day: limits.new_account_per_day, new_account_days: limits.new_account_days });
    }
    return t('publish.new.limits_settled', base);
}

export function limitSentences(limits: Limits, t: Translate, now: number): string[] {
    const lines: string[] = [];
    const { per_day, open_max, new_account_per_day, new_account_days, appeals_max, strikes, strikes_max, media_per_day } = limits;
    if (per_day !== null && open_max !== null) lines.push(t('publish.page.limits.per_day', { per_day, open_max }));
    if (new_account_per_day !== null && new_account_days !== null) lines.push(t('publish.page.limits.new_accounts', { days: new_account_days, per_day: new_account_per_day }));
    if (appeals_max !== null) lines.push(t('publish.page.limits.appeals', { count: appeals_max }));
    if (strikes_max !== null) lines.push(t('publish.page.limits.cooldown', { strikes_max }));
    if (media_per_day !== null) lines.push(t('publish.page.limits.images', { media_per_day }));
    if (strikes !== null && strikes_max !== null && strikes > 0) lines.push(t('publish.page.limits.strikes', { strikes, strikes_max }));
    const until = toDate(limits.cooldown_until);
    if (until && until.getTime() > now) lines.push(t('publish.page.limits.cooldown_now', { date: dateText(limits.cooldown_until, t) }));
    lines.push(t('publish.page.limits.hint'));
    return lines;
}

export function kindPanel(rules: Rules | null, t: Translate): KindRow[] {
    if (!rules) return [];
    const openOf = new Map<KindTab, boolean>();
    for (const entry of rules.kinds) {
        const tab = (KIND_TABS as readonly string[]).includes(entry.kind) ? (entry.kind as KindTab) : tabOf(entry.kind);
        if (tab) openOf.set(tab, (openOf.get(tab) ?? false) || entry.open);
    }
    return KIND_TABS.filter((tab) => openOf.has(tab)).map((tab) => {
        const word = KIND_WORD[tab];
        const open = openOf.get(tab) === true;
        const text = open
            ? t('publish.page.rules.kind_line', { what: t(`publish.page.kinds.${word}.what`), rules: t(`publish.page.kinds.${word}.rules`), folder: t(folderPhrase(tab)) })
            : t('publish.page.kinds.closed', { kind: t(`publish.page.tab.${tab}`) });
        return { tab, word, open, text };
    });
}
