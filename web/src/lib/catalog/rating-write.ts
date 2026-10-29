import type { ItemRatingWrite } from './types';
import { MAX_STARS, MIN_STARS } from './ratings';

export const STAR_VALUES: readonly number[] = [1, 2, 3, 4, 5];

export const MAX_RATING_TEXT = 2000;

export type RateBlocked = 'signed_out' | 'not_installed' | null;

export function rateBlocked(signedIn: boolean, installed: boolean = true): RateBlocked {
    if (!signedIn) return 'signed_out';
    return installed ? null : 'not_installed';
}

export function canSubmit(
    stars: number | null,
    working: boolean,
    signedIn: boolean,
): boolean {
    if (!signedIn || working) return false;
    if (typeof stars !== 'number' || !Number.isFinite(stars)) return false;
    return stars >= MIN_STARS && stars <= MAX_STARS;
}

export function clampText(value: string): string {
    if (typeof value !== 'string') return '';
    return value.trim().slice(0, MAX_RATING_TEXT);
}

export function yourStarsOf(body: ItemRatingWrite | null | undefined): number | null {
    if (!body || typeof body !== 'object') return null;
    const value = body.your_stars;
    if (typeof value !== 'number' || !Number.isFinite(value)) return null;
    return value;
}

export function removedOf(body: ItemRatingWrite | null | undefined): boolean | null {
    if (!body || typeof body !== 'object') return null;
    const value = body.removed;
    return typeof value === 'boolean' ? value : null;
}
