
export type PackStatKey = 'cpu' | 'ram' | 'disk';

export interface StatFit {
    show: Record<PackStatKey, boolean>;
    truncate: boolean;
}

const GIVE_WAY: PackStatKey[] = ['disk', 'ram'];

export function fitStats(available: number, nameWidth: number, widths: Record<PackStatKey, number>, gap: number): StatFit {
    const show: Record<PackStatKey, boolean> = { cpu: true, ram: true, disk: true };
    const total = (): number => {
        const on = (Object.keys(show) as PackStatKey[]).filter((k) => show[k]);
        return nameWidth + gap + on.reduce((n, k) => n + widths[k], 0) + gap * (on.length - 1);
    };
    for (const k of GIVE_WAY) {
        if (total() <= available) break;
        show[k] = false;
    }
    return { show, truncate: total() > available };
}

export function fitRows(root: HTMLElement): void {
    for (const main of Array.from(root.querySelectorAll<HTMLElement>('.sb-pack-row__main'))) {
        const name = main.querySelector<HTMLElement>('.sb-pack-row__name');
        const group = main.querySelector<HTMLElement>('.sb-pack-row__stats[data-stats="numbers"]');
        if (!name || !group) continue;
        const stats = Array.from(group.querySelectorAll<HTMLElement>('[data-stat]'));
        for (const s of stats) s.removeAttribute('data-hide');
        const keep = name.style.flex;
        name.style.flex = 'none';
        const nameWidth = name.offsetWidth;
        name.style.flex = keep;
        const cs = getComputedStyle(main);
        const gap = parseFloat(cs.columnGap) || 0;
        const innerGap = parseFloat(getComputedStyle(group).columnGap) || 0;
        const content = main.clientWidth - (parseFloat(cs.paddingLeft) || 0) - (parseFloat(cs.paddingRight) || 0);
        const others = Array.from(main.children).filter((c) => c !== name && c !== group) as HTMLElement[];
        const available = content - others.reduce((n, c) => n + c.offsetWidth + gap, 0);
        const widths = { cpu: 0, ram: 0, disk: 0 } as Record<PackStatKey, number>;
        for (const s of stats) widths[s.dataset.stat as PackStatKey] = s.offsetWidth;
        const fit = fitStats(available, nameWidth, widths, Math.max(gap, innerGap));
        for (const s of stats) if (!fit.show[s.dataset.stat as PackStatKey]) s.setAttribute('data-hide', '');
    }
}
