/** @vitest-environment jsdom */
import { flushSync } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ROW_ITEMS } from '../item-menu/menus/row-items';
import type { RowMenuCtx } from '../item-menu/row-context';
import { showPath } from './show-path';

const FOLDER = '/Users/me/Sync/Development/CloudeCode';

afterEach(() => {
    document.body.innerHTML = '';
    vi.restoreAllMocks();
});

describe('show path', () => {
    it('is offered on a session row and not on a sessionless one', () => {
        const item = ROW_ITEMS.find((i) => i.id === 'show-path');
        expect(item).toBeDefined();
        const ctx = (kind: string): RowMenuCtx => ({ kind } as unknown as RowMenuCtx);
        expect(item!.available(ctx('session'))).toBe(true);
        expect(item!.available(ctx('browser'))).toBe(false);
        expect(item!.available(ctx('layout'))).toBe(false);
    });

    it('shows the full folder and copies exactly that text', async () => {
        const writeText = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });

        const closed = showPath(FOLDER, 'api');
        flushSync();
        const value = document.querySelector('[data-show-path-value]');
        expect(value?.textContent).toBe(FOLDER);

        (document.querySelector('[data-show-path-copy]') as HTMLButtonElement).click();
        await vi.waitFor(() => expect(writeText).toHaveBeenCalledWith(FOLDER));
        await vi.waitFor(() => expect(document.querySelector('[data-show-path-copy]')?.textContent).toBe('copied'));

        (document.querySelector('[data-show-path-close]') as HTMLButtonElement).click();
        await closed;
        expect(document.querySelector('[data-show-path-modal]')).toBeNull();
    });
});
