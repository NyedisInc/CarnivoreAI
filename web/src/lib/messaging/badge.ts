
export interface MessagingMark {
    readonly directions: readonly string[];
    readonly held: number;
}

export type BadgeDirection = 'in' | 'out' | 'both';

export interface BadgePlan {
    readonly direction: BadgeDirection;
    readonly held: number;
    readonly title: string;
    readonly tone: 'bound' | 'held';
}

type Translate = (key: string, params?: Record<string, unknown>) => string;

function directionOf(directions: readonly string[]): BadgeDirection | null {
    const hasIn = directions.includes('in');
    const hasOut = directions.includes('out');
    if (hasIn && hasOut) return 'both';
    if (hasIn) return 'in';
    if (hasOut) return 'out';
    return null;
}

export function badgePlan(mark: unknown, t: Translate): BadgePlan | null {
    if (!mark || typeof mark !== 'object') return null;
    const { directions, held } = mark as Partial<MessagingMark>;
    const dir = directionOf(Array.isArray(directions) ? directions : []);
    if (!dir) return null;
    const count = typeof held === 'number' && held > 0 ? Math.floor(held) : 0;
    const title = t(`messaging.ui.badge.title.${dir}`);
    if (count > 0) {
        return { direction: dir, held: count, title: `${title}. ${t('messaging.ui.badge.held_title', { count })}`, tone: 'held' };
    }
    return { direction: dir, held: 0, title, tone: 'bound' };
}
