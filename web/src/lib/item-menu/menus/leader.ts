import { wakeAgent } from '../../../cplugs/huddle/chat/chat-api';
import { t } from '../../i18n/index.svelte';
import { act, rename, turnOff } from '../../sidebar-shell/leader-ghost';
import { hg } from '../../sidebar-shell/interaction-globals';
import { entryNodes, type ItemMenuEntry } from '../entries';
import { defineItemMenu } from '../registry';

defineItemMenu('leader', {
    build({ ghost: g }, env) {
        const icons = hg().SessionRowMenuIcons;
        const entries: ItemMenuEntry[] = [
            { label: t('leader.menu.wake'), icon: icons ? 'wake' : undefined, id: 'wake', onPick: () => { void act(g, () => wakeAgent(g.agentId, 'resume')); } },
            { label: t('leader.rename.menu'), icon: 'rename', id: 'rename-agent', onPick: () => { void rename(g); } },
        ];
        if (g.rank !== 'alpha') entries.push({ label: t('leader.menu.turn_off'), icon: 'close', id: 'turn-off-agent', onPick: () => { void turnOff(g); } });
        return { nodes: entryNodes(entries, env.glyph, env.close), ariaLabel: t('leader.menu.label', { name: g.name }) };
    },
});
