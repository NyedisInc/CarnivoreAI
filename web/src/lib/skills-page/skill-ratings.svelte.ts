import type { CatalogHost } from '../catalog/catalog';
import { ratingsView } from '../catalog/ratings';

export interface CardRating {
    shape: 'rated' | 'none';
    average: number | null;
    count: number;
    comments: number;
}

const CONCURRENCY = 4;

class SkillRatings {
    byId = $state<Record<string, CardRating>>({});
    #asked = new Set<string>();
    #queue: string[] = [];
    #running = 0;

    want(ids: readonly string[], host: Pick<CatalogHost, 'itemRatings'>): void {
        for (const id of ids) {
            if (this.#asked.has(id)) continue;
            this.#asked.add(id);
            this.#queue.push(id);
        }
        while (this.#running < CONCURRENCY && this.#queue.length > 0) void this.#next(host);
    }

    async #next(host: Pick<CatalogHost, 'itemRatings'>): Promise<void> {
        const id = this.#queue.shift();
        if (!id) return;
        this.#running += 1;
        try {
            const view = ratingsView(await host.itemRatings(id));
            if (view.shape === 'rated' || view.shape === 'none') {
                this.byId = {
                    ...this.byId,
                    [id]: { shape: view.shape, average: view.average, count: view.count ?? 0, comments: view.texts.filter((r) => r.text).length },
                };
            }
        } catch {
        } finally {
            this.#running -= 1;
            if (this.#queue.length > 0) void this.#next(host);
        }
    }
}

export const skillRatings = new SkillRatings();
