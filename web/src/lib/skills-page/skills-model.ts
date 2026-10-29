/* the detail pane */
import type { ManagerItem } from '../manager-frame/types';
import { providerMark } from '../sessions/agent-marks';
import type { Translate } from '../sessions/types';
import type {
    Inventory,
    OverrideFile,
    ProfileGroupRow,
    SkillGroupRow,
    SkillLocationRow,
} from './skills-types';

export const HEAVY_TOKENS = 100;

const BRIEF_CHARS = 260;

export interface ContextChoice {
    /* <path> */
    readonly id: string;
    readonly kind: 'global' | 'profile' | 'project';
    readonly label: string;
    readonly projectPath: string | null;
    readonly profile: string | null;
}

export interface ProjectRef {
    readonly name: string;
    readonly path: string;
    readonly root?: string | null;
    readonly archived_at?: string | null;
}

export const GLOBAL_CONTEXT_ID = 'global';

export function contextChoices(
    groups: readonly ProfileGroupRow[],
    globalGroupId: string | null,
    projects: readonly ProjectRef[],
    t: Translate,
): ContextChoice[] {
    const out: ContextChoice[] = [
        { id: GLOBAL_CONTEXT_ID, kind: 'global', label: t('skills.page.context.global'), projectPath: null, profile: null },
    ];
    for (const group of groups) {
        if (group.group_id === globalGroupId || group.profiles.length === 0) continue;
        const names = group.profiles.join(', ');
        out.push({
            id: `profile:${group.profiles[0]}`,
            kind: 'profile',
            label: group.own_folder ? t('skills.page.context.own_folder', { profiles: names }) : t('skills.page.context.profile', { profiles: names }),
            projectPath: null,
            profile: group.profiles[0] ?? null,
        });
    }
    const live = projects.filter((p) => !p.archived_at);
    for (const project of [...live].sort((a, b) => a.name.localeCompare(b.name))) {
        const path = project.root || project.path;
        out.push({ id: `project:${path}`, kind: 'project', label: project.name, projectPath: path, profile: null });
    }
    return out;
}

export const CLAUDE_STATE_KEYS: Readonly<Record<string, string>> = {
    on: 'skills.state.on',
    'name-only': 'skills.state.compact',
    'user-invocable-only': 'skills.state.on_demand',
    off: 'skills.state.off',
};

export interface SkillItem extends ManagerItem {
    readonly group: SkillGroupRow;
    readonly harnesses: readonly ('claude' | 'codex')[];
    readonly states: Readonly<Partial<Record<'claude' | 'codex', string>>>;
    readonly tokens: number;
    readonly shadowed: boolean;
    readonly off: boolean;
    readonly heavy: boolean;
}

function cardImagePath(locs: readonly SkillLocationRow[]): string | undefined {
    const art = (locs.find((l) => effective(l) && l.card_art) ?? locs.find((l) => l.card_art))?.card_art;
    return art ? `/skills/card-art/${art.id}${art.rev ? `?rev=${encodeURIComponent(art.rev)}` : ''}` : undefined;
}

function effective(loc: SkillLocationRow): boolean {
    return loc.shadowed_by === null;
}

export function switchable(loc: SkillLocationRow, context: ContextChoice): boolean {
    if (loc.toggle.kind === 'none' || loc.read_only) return false;
    if (loc.harness === 'claude') return effective(loc);
    if (context.kind === 'global') return true;
    return context.kind === 'project' && loc.scope === 'project';
}

export function targetFile(context: ContextChoice, harness: 'claude' | 'codex'): OverrideFile {
    if (context.kind !== 'project') return 'user';
    return harness === 'claude' ? 'local' : 'project';
}

/* and writes nothing */
export function stateToSend(
    choice: string,
    source: string | null,
    file: OverrideFile,
    harness: 'claude' | 'codex',
): string | null | undefined {
    if (choice !== 'on') return choice;
    if (harness === 'codex') return source === null ? undefined : null;
    if (source === null) return undefined;
    return source === file ? null : 'on';
}

export interface PlannedWrite {
    readonly harness: 'claude' | 'codex';
    readonly file: OverrideFile;
    readonly state: string | null;
}

/* the detail pane */
export function planWrites(
    group: SkillGroupRow,
    context: ContextChoice,
    choice: string,
    harness?: 'claude' | 'codex',
): PlannedWrite[] {
    const out: PlannedWrite[] = [];
    for (const h of ['claude', 'codex'] as const) {
        if (harness && harness !== h) continue;
        const loc = group.locations.find((l) => l.harness === h && switchable(l, context));
        if (!loc) continue;
        if (h === 'codex' && choice !== 'on' && choice !== 'off') continue;
        const file = targetFile(context, h);
        if (loc.state === choice) continue;
        const state = stateToSend(choice, loc.state_source, file, h);
        if (state === undefined) continue;
        out.push({ harness: h, file, state });
    }
    return out;
}

function briefOf(text: string): string {
    const flat = text.replace(/\s+/g, ' ').trim();
    return flat.length > BRIEF_CHARS ? `${flat.slice(0, BRIEF_CHARS - 1)}...` : flat;
}

function briefFor(locs: readonly SkillLocationRow[]): string {
    const pick = (field: 'card_summary' | 'card_lead'): string | undefined =>
        (locs.find((l) => effective(l) && l[field]) ?? locs.find((l) => l[field]))?.[field] ?? undefined;
    const lead = pick('card_summary') ?? pick('card_lead');
    if (lead) return lead;
    if (locs.some((l) => l.card_lead !== undefined)) return '';
    return briefOf(locs[0]?.description ?? '');
}

export function toItems(inventory: Inventory, context: ContextChoice, t: Translate): SkillItem[] {
    return inventory.skills.map((group) => {
        const locs = group.locations;
        const harnesses = (['claude', 'codex'] as const).filter((h) => locs.some((l) => l.harness === h));
        const states: Partial<Record<'claude' | 'codex', string>> = {};
        for (const h of harnesses) {
            const loc = locs.find((l) => l.harness === h && effective(l)) ?? locs.find((l) => l.harness === h);
            if (loc) states[h] = loc.state;
        }
        const tokens = Math.max(...locs.map((l) => l.description_tokens_est));
        const switches = locs.filter((l) => switchable(l, context));
        const enabled = switches.length === 0 ? null : switches.some((l) => l.state !== 'off');
        const off = locs.some((l) => effective(l) && l.state === 'off');
        const shadowed = locs.some((l) => l.shadowed_by !== null);
        const marks: string[] = harnesses.map((h) => t(`skills.harness.${h}`));
        for (const h of harnesses) {
            const state = states[h];
            if (state && state !== 'on' && state !== 'off') marks.push(t(CLAUDE_STATE_KEYS[state] ?? state));
        }
        if (shadowed) marks.push(t('skills.mark.shadowed'));
        if (locs.every((l) => l.scope === 'plugin')) marks.push(t('skills.mark.plugin'));
        const managedBy = locs.map((l) => l.managed).find((m) => m !== null) ?? null;
        const isLocal = locs.every((l) => l.managed === null && l.scope !== 'plugin' && l.scope !== 'system');
        const itemId = managedBy?.item_id ?? '';
        const publisher = itemId.includes('/') ? (itemId.split('/')[0] ?? '') : '';
        return {
            id: group.name,
            name: group.name,
            brief: briefFor(locs),
            marks,
            icon: 'skill',
            imagePath: cardImagePath(locs),
            iconSvg: providerMark(harnesses[0] ?? null, 16).svg,
            status: shadowed
                ? { label: t('skills.status.shadowed'), tone: 'warn' }
                : off
                  ? { label: t('skills.status.off'), tone: 'off' }
                  : { label: t('skills.status.on'), tone: 'on' },
            tags: managedBy ? [t('skills.tag.managed')] : isLocal ? [t('skills.tag.local')] : [],
            byline: publisher ? t('skills.byline', { publisher }) : null,
            enabled,
            group,
            harnesses,
            states,
            tokens,
            shadowed,
            off,
            heavy: tokens >= HEAVY_TOKENS,
        };
    });
}
