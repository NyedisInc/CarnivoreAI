import { tabOf } from './kinds';
import { heldKey, type HeldReason } from './keys';
import type { ActionResult } from './actions';
import type { Limits, Rules } from './types';

export const VERSION_RE = /^\d+\.\d+\.\d+$/;

export const FIRST_VERSION = '1.0.0';

function partsOf(version: string): [number, number, number] {
    const parts = version.split('.').map((p) => Number.parseInt(p, 10));
    return [parts[0] || 0, parts[1] || 0, parts[2] || 0];
}

export function compareVersions(a: string, b: string): number {
    const x = partsOf(a);
    const y = partsOf(b);
    return x[0] - y[0] || x[1] - y[1] || x[2] - y[2];
}

export function bumpPatch(version: string): string {
    const [major, minor, patch] = partsOf(version);
    return `${major}.${minor}.${patch + 1}`;
}

export function highestVersion(versions: readonly string[]): string {
    return versions.reduce((best, v) => (best === '' || compareVersions(v, best) > 0 ? v : best), '');
}

export function defaultVersion(declared: string, sent: readonly string[]): string {
    const top = highestVersion(sent);
    if (top !== '' && (declared === '' || compareVersions(declared, top) <= 0)) return bumpPatch(top);
    return declared || FIRST_VERSION;
}

export interface HeldContext {
    signedIn: boolean;
    registered: boolean | null;
    kind: string;
    rules: Rules | null;
    limits: Limits | null;
    checked: { version: string; canSend: boolean } | null;
    version: string;
    sentVersions: readonly string[];
    wantsImage: boolean;
    now: number;
}

export interface Held { reason: HeldReason; blocks: boolean }

export function dayCap(limits: Limits | null): number | null {
    if (!limits || limits.per_day === null) return null;
    if (limits.new_account && limits.new_account_per_day !== null) return Math.min(limits.per_day, limits.new_account_per_day);
    return limits.per_day;
}

export function heldReasons(c: HeldContext): Held[] {
    const out: Held[] = [];
    const add = (reason: HeldReason, blocks = true): void => { out.push({ reason, blocks }); };
    const l = c.limits;
    if (!c.signedIn) add('signed_out');
    if (c.signedIn && c.registered === false) add('need_handle');
    const tab = tabOf(c.kind);
    const rule = c.rules?.kinds.find((k) => k.kind === tab);
    if (rule && !rule.open) add('kind_closed');
    if (l && l.cooldown_until !== '' && Date.parse(l.cooldown_until) > c.now) add('cooldown');
    const cap = dayCap(l);
    if (l && cap !== null && l.used_today !== null && l.used_today >= cap) add('day_limit');
    if (l && l.open_max !== null && l.open_now !== null && l.open_now >= l.open_max) add('open_limit');
    if (l && c.wantsImage && l.media_per_day !== null && l.media_used_today !== null && l.media_used_today >= l.media_per_day) add('image_limit', false);
    if (!c.checked) add('not_checked');
    else if (!c.checked.canSend) add('folder_refused');
    else if (c.checked.version !== c.version) add('version_changed');
    if (c.sentVersions.includes(c.version)) add('version_exists');
    return out;
}

export function heldReason(c: HeldContext): HeldReason | null {
    return heldReasons(c).find((h) => h.blocks)?.reason ?? null;
}

export function heldParams(limits: Limits | null, kindWord: string, date: string, kindsWord = kindWord): Record<string, string | number> {
    return {
        kind: kindWord,
        kinds: kindsWord,
        date,
        per_day: dayCap(limits) ?? 0,
        new_account_per_day: limits?.new_account_per_day ?? 0,
        new_account_days: limits?.new_account_days ?? 0,
        open: limits?.open_now ?? 0,
        open_max: limits?.open_max ?? 0,
    };
}

export function heldCall(key: string, params: Record<string, string | number>): [string, Record<string, string | number>] {
    if (key.endsWith('.held.day_limit')) return [key, { ...params, count: params.per_day ?? 0 }];
    if (key.endsWith('.held.open_limit')) return [key, { ...params, count: params.open ?? 0 }];
    if (key.endsWith('.held.cooldown') && !params.date) return [`${key}_undated`, params];
    return [key, params];
}

const REFUSED = ['kind_closed', 'name_taken', 'name_pending', 'version_exists', 'kind_mismatch', 'rate_limited', 'open_limit', 'cooldown', 'folder_refused', 'folder_changed'] as const;

export function refusalKey(code: string): string | null {
    return (REFUSED as readonly string[]).includes(code) ? heldKey(code as HeldReason) : null;
}

export function needsRecheck(code: string): boolean {
    return code === 'folder_changed';
}

export type ImagePlan = 'none' | 'own' | 'made';

export type HeroOutcome = 'none' | 'making' | 'sent' | 'failed';

export interface SendPlan {
    image: ImagePlan;
    send(): Promise<ActionResult<{ submission_id?: string; item_id?: string }>>;
    imageBase64(): Promise<string | null>;
    media(imageBase64: string): Promise<ActionResult<unknown>>;
    onHero?(state: HeroOutcome): void;
}

export interface SendOutcome {
    sent: ActionResult<{ submission_id?: string; item_id?: string }>;
    hero: HeroOutcome;
}

export async function runSend(plan: SendPlan): Promise<SendOutcome> {
    const sent = await plan.send();
    if (!sent.ok || plan.image === 'none') return { sent, hero: 'none' };
    plan.onHero?.('making');
    let image: string | null = null;
    try {
        image = await plan.imageBase64();
    } catch {
        image = null;
    }
    if (image === null) return { sent, hero: 'failed' };
    const media = await plan.media(image);
    return { sent, hero: media.ok ? 'sent' : 'failed' };
}
