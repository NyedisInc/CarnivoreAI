
export type LaunchSource =
    | { kind: 'project'; name: string }
    | { kind: 'session'; name: string; pinned?: boolean }
    | { kind: 'task'; title: string };

export interface LaunchPrefill { name: string; pinned: boolean }

export const TASK_NAME_MAX = 40;

export function nextFreeName(base: string, taken: readonly string[]): string {
    const used = new Set(taken.map((n) => n.trim().toLowerCase()));
    const stem = base.trim().replace(/\s+\d+$/, '') || base.trim();
    if (!used.has(base.trim().toLowerCase())) return base.trim();
    const startsAt = /\s+(\d+)$/.exec(base.trim());
    let n = startsAt ? Number(startsAt[1]) + 1 : 2;
    while (used.has(`${stem} ${n}`.toLowerCase())) n += 1;
    return `${stem} ${n}`;
}

export function shortTaskName(title: string): string {
    const line = (title.split('\n')[0] ?? '').replace(/\s+/g, ' ').trim();
    if (line.length <= TASK_NAME_MAX) return line;
    const cut = line.slice(0, TASK_NAME_MAX);
    const space = cut.lastIndexOf(' ');
    return (space > TASK_NAME_MAX / 2 ? cut.slice(0, space) : cut).replace(/[\s.,:;-]+$/, '');
}

export function prefillFor(source: LaunchSource | null, taken: readonly string[]): LaunchPrefill {
    if (!source) return { name: '', pinned: false };
    if (source.kind === 'project') return { name: source.name.trim(), pinned: false };
    if (source.kind === 'session') return { name: nextFreeName(source.name, taken), pinned: source.pinned === true };
    return { name: shortTaskName(source.title), pinned: false };
}

/* the project row */
export function sourceOfProject(project: { name?: unknown; launch_from?: unknown }): LaunchSource | null {
    const from = project.launch_from as Partial<LaunchSource> | undefined;
    if (from && from.kind === 'session' && typeof from.name === 'string') return { kind: 'session', name: from.name, pinned: (from as { pinned?: boolean }).pinned === true };
    if (from && from.kind === 'task' && typeof (from as { title?: unknown }).title === 'string') return { kind: 'task', title: (from as { title: string }).title };
    return typeof project.name === 'string' && project.name.trim() ? { kind: 'project', name: project.name } : null;
}
