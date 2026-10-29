
export type TypeAction =
    | { readonly type: 'next' }
    | { readonly type: 'prev' }
    | { readonly type: 'open-soon' }
    | { readonly type: 'panel' }
    | { readonly type: 'jump'; readonly prefix: string }
    | { readonly type: 'none' };

export const BUFFER_MS = 900;
export const OPEN_DELAY_MS = 350;

export class TypeAhead {
    #buf = '';
    #at = 0;

    get buffer(): string {
        return this.#buf;
    }

    get commandOnly(): boolean {
        return /^[jko]*$/.test(this.#buf);
    }

    press(ch: string, now: number, hasHit: (prefix: string) => boolean): TypeAction {
        const live = this.#buf !== '' && now - this.#at < BUFFER_MS;
        if (!live) this.#buf = '';
        const command = ch === 'j' || ch === 'k' || ch === 'o';
        if (command && this.commandOnly) {
            this.#buf += ch;
            this.#at = now;
            return ch === 'j' ? { type: 'next' } : ch === 'k' ? { type: 'prev' } : { type: 'open-soon' };
        }
        if (!live && ch === ' ') return { type: 'panel' };
        this.#buf += ch.toLowerCase();
        this.#at = now;
        if (hasHit(this.#buf)) return { type: 'jump', prefix: this.#buf };
        if (this.#buf.length > 1) {
            this.#buf = ch.toLowerCase();
            return hasHit(this.#buf) ? { type: 'jump', prefix: this.#buf } : { type: 'none' };
        }
        return { type: 'none' };
    }
}
