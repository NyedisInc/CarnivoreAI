/* could not */
import { clipChars } from './bounds';
import type { ItemRatings, RatingReview } from './types';

export const MIN_STARS = 1;
export const MAX_STARS = 5;

export const MAX_REVIEWS = 20;

export const MAX_REVIEW_CHARS = 2000;

export const MAX_LOGIN_CHARS = 39;

export type RatingsShape = 'unavailable' | 'none' | 'rated';

export interface HistogramRow {
    stars: number;
    count: number;
    percent: number;
}

export interface RatingTextView {
    login: string | null;
    stars: number | null;
    text: string | null;
    updatedAt: number | null;
    author: string | null;
    publisher: boolean;
    reviewRef: string | null;
    reportedInstalling: boolean;
}

export interface RatingsView {
    shape: RatingsShape;
    count: number | null;
    average: number | null;
    histogram: HistogramRow[];
    texts: RatingTextView[];
    /* could not nothing at all */
    textsMalformed: boolean;
}

function numberOf(value: unknown): number | null {
    if (typeof value !== 'number' || !Number.isFinite(value)) return null;
    return value;
}

function bounded(value: unknown, limit: number): string | null {
    if (typeof value !== 'string') return null;
    const trimmed = value.trim();
    return trimmed ? clipChars(trimmed, limit) : null;
}

export function histogramRows(
    histogram: Record<string, number> | null | undefined,
    total: number,
): HistogramRow[] {
    const source = histogram && typeof histogram === 'object' ? histogram : {};
    const rows: HistogramRow[] = [];
    for (let stars = MAX_STARS; stars >= MIN_STARS; stars -= 1) {
        const raw = numberOf((source as Record<string, unknown>)[String(stars)]);
        // could not be read
        const count = raw === null || raw < 0 ? 0 : Math.trunc(raw);
        const percent = total > 0 ? Math.round((count / total) * 100) : 0;
        rows.push({ stars, count, percent });
    }
    return rows;
}

function textsOf(raw: unknown): RatingTextView[] | null {
    if (!Array.isArray(raw)) return null;
    const texts: RatingTextView[] = [];
    for (const entry of raw) {
        if (texts.length >= MAX_REVIEWS) break;
        const review = (entry || {}) as RatingReview;
        texts.push({
            login: bounded(review.login, MAX_LOGIN_CHARS),
            stars: numberOf(review.stars),
            text: bounded(review.text, MAX_REVIEW_CHARS),
            updatedAt: numberOf(review.updated_at),
            author: bounded(review.author, MAX_LOGIN_CHARS),
            publisher: review.publisher === true,
            reviewRef: bounded(review.review_ref, 64),
            reportedInstalling: review.reported_installing === true,
        });
    }
    return texts;
}

export function ratingsView(body: ItemRatings | null | undefined): RatingsView {
    const empty: RatingsView = {
        shape: 'unavailable',
        count: null,
        average: null,
        histogram: histogramRows(null, 0),
        texts: [],
        textsMalformed: false,
    };
    if (!body || typeof body !== 'object') return empty;

    const count = numberOf(body.count);
    if (count === null || count < 0) return empty;

    const texts = textsOf(body.reviews);
    return {
        shape: count === 0 ? 'none' : 'rated',
        count,
        average: count === 0 ? null : numberOf(body.average),
        histogram: histogramRows(body.histogram, count),
        texts: texts ?? [],
        textsMalformed: texts === null,
    };
}
