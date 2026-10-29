import { openSwarmAgentTerminal, renameSwarmAgent, turnOffSwarmAgent, wakeSwarmAgent } from '../../cplugs/sdk/swarm-agent-actions';
import { refreshSwarmRoster } from '../../cplugs/sdk/swarm-roster.svelte';
import { askLeaderConfirm } from '../leader-confirm/confirm';
import { t } from '../i18n/index.svelte';
import { announceFailure, reasonOf } from './interaction-globals';
import { openItemMenu } from '../item-menu/open.svelte';
import type { LeaderRank } from './leaders';

export interface GhostAgent {
    agentId: number;
    name: string;
    rank: LeaderRank;
}

export async function act(g: GhostAgent, run: () => Promise<void>): Promise<void> {
    try {
        await run();
    } catch (err) {
        announceFailure(t('leader.ghost.failed', { name: g.name, reason: reasonOf(err) }));
    }
    await refreshSwarmRoster();
}

export async function wake(g: GhostAgent): Promise<void> {
    await act(g, () => wakeSwarmAgent(g.agentId, 'resume'));
}

export async function rename(g: GhostAgent): Promise<void> {
    const prompter = (globalThis as { TextPromptModal?: { open(o: Record<string, string>): Promise<string | null> } }).TextPromptModal;
    const raw = await prompter?.open({
        title: t('leader.rename.title'), label: t('leader.rename.label'), defaultValue: g.name,
        confirmLabel: t('leader.rename.save'), cancelLabel: t('leader.confirm.cancel'),
    });
    const next = (raw ?? '').trim();
    if (!next || next === g.name) return;
    await act(g, () => renameSwarmAgent(g.agentId, next));
}

export async function turnOff(g: GhostAgent): Promise<void> {
    const typed = await askLeaderConfirm({ name: g.name, rank: g.rank, action: 'turn off' });
    if (typed === null) return;
    await act(g, () => turnOffSwarmAgent(g.agentId, typed));
}

export function openGhostMenu(anchor: Element, g: GhostAgent): void {
    openItemMenu('leader', { ghost: g, anchor }, anchor);
}

export function openGhostTerminal(event: MouseEvent, g: GhostAgent): void {
    if (!event.shiftKey) return;
    event.stopPropagation();
    void openSwarmAgentTerminal(g.agentId);
}
