import type { ManagerChip } from '../manager-frame/types';
import { providerMark } from '../sessions/agent-marks';
import type { Translate } from '../sessions/types';
import type { MarkerId } from './skill-state';
import type { SkillItem } from './skills-model';

const CHIP_ICONS: Readonly<Record<string, string>> = {
    carnivore: 'bolt',
    compact: 'shrink',
    on_demand: 'play',
    shadowed: 'copy',
    plugin: 'plug',
    drifted: 'cycle',
    missing: 'status-question',
    flagged: 'bell',
    unused: 'clock',
    managed: 'pack',
    local: 'folder',
};

export function chipsOf(item: SkillItem, markers: readonly MarkerId[], firstParty: boolean, t: Translate): ManagerChip[] {
    const out: ManagerChip[] = [];
    const named = (id: string): ManagerChip => ({ id, label: t(`skills.chip.${id}`), icon: CHIP_ICONS[id] });
    if (firstParty) out.push(named('carnivore'));
    for (const h of item.harnesses) out.push({ id: h, label: t(`skills.chip.${h}`), svg: providerMark(h, 14).svg });
    for (const h of item.harnesses) {
        const state = item.states[h];
        if (state === 'name-only') out.push(named('compact'));
        else if (state === 'user-invocable-only') out.push(named('on_demand'));
    }
    if (item.shadowed) out.push(named('shadowed'));
    if (item.group.locations.every((l) => l.scope === 'plugin')) out.push(named('plugin'));
    for (const m of markers) out.push(named(m));
    for (const tag of item.tags ?? []) {
        const id = tag === t('skills.tag.managed') ? 'managed' : 'local';
        out.push(named(id));
    }
    return out.filter((chip, i) => out.findIndex((c) => c.id === chip.id) === i);
}
