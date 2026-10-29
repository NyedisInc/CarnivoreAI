import type { PageStore } from './page-store.svelte';
import type { HeroOutcome } from './wizard-model';

export interface HeroChoice {
    mode: 'auto' | 'own';
    file: Blob | null;
    url: string | null;
    name: string;
    w: number;
    h: number;
    kb: number;
    err: string | null;
}

export interface Draft {
    version: string | null;
    phase: 'idle' | 'checking' | 'sending';
    err: string | null;
    refusal: string;
    hero: HeroChoice;
    heroOutcome: HeroOutcome;
}

const NO_HERO: HeroChoice = { mode: 'auto', file: null, url: null, name: '', w: 0, h: 0, kb: 0, err: null };
const BLANK: Draft = { version: null, phase: 'idle', err: null, refusal: '', hero: NO_HERO, heroOutcome: 'none' };

export class WizardDrafts {
    #map = $state<Record<string, Draft>>({});

    of(location: string): Draft {
        return this.#map[location] ?? BLANK;
    }

    patch(location: string, fields: Partial<Draft>): void {
        this.#map[location] = { ...this.of(location), ...fields };
    }

    chooseFile(location: string, file: Blob, meta: { name: string; w: number; h: number }): void {
        const old = this.of(location).hero;
        if (old.url) URL.revokeObjectURL(old.url);
        this.patch(location, {
            hero: { mode: 'own', file, url: URL.createObjectURL(file), name: meta.name, w: meta.w, h: meta.h, kb: Math.max(1, Math.round(file.size / 1024)), err: null },
        });
    }

    refuseFile(location: string, line: string): void {
        const old = this.of(location).hero;
        if (old.url) URL.revokeObjectURL(old.url);
        this.patch(location, { hero: { ...NO_HERO, mode: 'own', err: line } });
    }

    setMode(location: string, mode: 'auto' | 'own'): void {
        if (mode === 'own') this.patch(location, { hero: { ...this.of(location).hero, mode, err: null } });
        else this.discard(location);
    }

    discard(location: string): void {
        const old = this.of(location).hero;
        if (old.url) URL.revokeObjectURL(old.url);
        this.patch(location, { hero: NO_HERO });
    }

    afterSend(location: string, heroOutcome: HeroOutcome): void {
        const old = this.of(location).hero;
        if (old.url) URL.revokeObjectURL(old.url);
        this.patch(location, { version: null, phase: 'idle', err: null, refusal: '', hero: NO_HERO, heroOutcome });
    }
}

const BY_STORE = new WeakMap<PageStore, WizardDrafts>();

export function draftsOf(store: PageStore): WizardDrafts {
    let drafts = BY_STORE.get(store);
    if (!drafts) {
        drafts = new WizardDrafts();
        BY_STORE.set(store, drafts);
    }
    return drafts;
}
