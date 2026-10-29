import { openModal } from '../modal';
import { t } from '../i18n/index.svelte';
import ConfirmOkModal from './ConfirmOkModal.svelte';

export interface ConfirmOkOptions {
    title: string;
    message: string;
    okLabel?: string;
    cancelLabel?: string;
}

export const MIDDLE_BUTTON = 1;

export async function confirmOk(options: ConfirmOkOptions): Promise<boolean> {
    const answer = await openModal<boolean, { title: string; message: string; okLabel: string; cancelLabel: string }>(ConfirmOkModal, {
        title: options.title,
        message: options.message,
        okLabel: options.okLabel ?? t('confirm_ok.ok'),
        cancelLabel: options.cancelLabel ?? t('confirm_ok.cancel'),
    });
    return answer === true;
}

export function suppressMiddleAutoscroll(event: MouseEvent): void {
    if (event.button === MIDDLE_BUTTON) event.preventDefault();
}

export function onMiddleClick(event: MouseEvent, run: () => void): boolean {
    if (event.button !== MIDDLE_BUTTON) return false;
    event.preventDefault();
    event.stopPropagation();
    run();
    return true;
}
