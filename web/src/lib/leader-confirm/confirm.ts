import { openModal } from '../modal';
import { t } from '../i18n/index.svelte';
import LeaderConfirm from './LeaderConfirm.svelte';

export interface LeaderAsk {
    name: string;
    rank: string;
    action?: string;
}

export function askLeaderConfirm(ask: LeaderAsk): Promise<string | null> {
    const verb = ask.action === 'turn off' ? t('leader.confirm.verb.turn_off') : t('leader.confirm.verb.close');
    return openModal<string, { name: string; rank: string; verb: string }>(LeaderConfirm, { name: ask.name, rank: ask.rank, verb });
}
