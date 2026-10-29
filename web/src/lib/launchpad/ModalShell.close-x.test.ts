/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';

import { openModal, openModalCount } from '../modal';
import ChoiceModal from './ChoiceModal.svelte';
import ProjectNameModal from './ProjectNameModal.svelte';
import type { ChoiceItem, ProjectDetails } from './modal-types';

afterEach(() => {
    document.body.innerHTML = '';
});

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
}

function overlay(): HTMLElement | null {
    return document.querySelector('.modal-overlay');
}

describe('every default ModalShell header carries the X', () => {
    test('the choice modal: a click on the X cancels, same as escape', async () => {
        const promise = openModal<string, Record<string, unknown>>(ChoiceModal as never, {
            title: 'pick one',
            items: [{ key: 'a', label: 'the a' }] as ChoiceItem[],
        });
        await settle();
        const closeBtn = overlay()!.querySelector<HTMLButtonElement>('[data-modal-close]');
        expect(closeBtn).not.toBe(null);
        expect(closeBtn!.getAttribute('aria-label')).toBeTruthy();
        expect(closeBtn!.disabled).toBe(false);
        closeBtn!.click();
        expect(await promise).toBe(null);
        expect(overlay()).toBe(null);
        expect(openModalCount()).toBe(0);
    });

    test('a custom-head consumer (project name) carries the same X', async () => {
        const promise = openModal<ProjectDetails, Record<string, unknown>>(
            ProjectNameModal as never,
            { title: 'name this project', confirmLabel: 'create session' },
        );
        await settle();
        const closeBtn = overlay()!.querySelector<HTMLButtonElement>('.text-prompt-modal__head [data-modal-close]');
        expect(closeBtn).not.toBe(null);
        closeBtn!.click();
        expect(await promise).toBe(null);
    });
});
