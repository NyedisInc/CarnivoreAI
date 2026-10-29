/* the widgets page */
import { visibilityObserver } from '../visibility-observer';

export const PREVIEW_CAP = 12;

interface Tile {
    el: Element;
    inView: boolean;
    held: boolean;
    grant: (on: boolean) => void;
}

const tiles = new Map<Element, Tile>();
let heldCount = 0;
let observer: IntersectionObserver | null = null;

function byDom(a: Tile, b: Tile): number {
    return a.el.compareDocumentPosition(b.el) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
}

function fill(): void {
    if (heldCount >= PREVIEW_CAP) return;
    const waiting = [...tiles.values()].filter((tile) => tile.inView && !tile.held).sort(byDom);
    for (const tile of waiting) {
        if (heldCount >= PREVIEW_CAP) break;
        tile.held = true;
        heldCount += 1;
        tile.grant(true);
    }
}

function giveUp(tile: Tile): void {
    if (tile.held) {
        tile.held = false;
        heldCount -= 1;
        tile.grant(false);
    }
    tile.inView = false;
}

function shared(): IntersectionObserver | null {
    if (observer) return observer;
    const Observer = visibilityObserver();
    if (!Observer) return null;
    observer = new Observer((entries) => {
        for (const entry of entries) {
            const tile = tiles.get(entry.target);
            if (!tile) continue;
            if (entry.isIntersecting) tile.inView = true;
            else giveUp(tile);
        }
        fill();
    }, { rootMargin: '0px' });
    return observer;
}

export function trackPreview(el: Element, grant: (on: boolean) => void): () => void {
    const watch = shared();
    if (!watch) return () => {};
    const tile: Tile = { el, inView: false, held: false, grant };
    tiles.set(el, tile);
    watch.observe(el);
    return () => {
        watch.unobserve(el);
        giveUp(tile);
        tiles.delete(el);
        fill();
    };
}

export function previewSlotsHeld(): number {
    return heldCount;
}
