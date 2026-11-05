import { openModal } from '../modal';
import { t } from '../i18n/index.svelte';
import ConfirmOkModal from './ConfirmOkModal.svelte';

export type ConfirmVariant = 'plain' | 'danger';

export interface ConfirmOkOptions {
    title: string;
    message: string;
    details?: string | null;
    okLabel?: string;
    cancelLabel?: string;
    variant?: ConfirmVariant;
}

/* download saved copy */
export interface ConfirmChoiceOptions extends ConfirmOkOptions {
    altLabel: string;
}

export type ConfirmChoice = 'ok' | 'alt' | 'cancel';

interface ModalProps extends Record<string, unknown> {
    title: string;
    message: string;
    details: string;
    okLabel: string;
    cancelLabel: string;
    altLabel: string;
    variant: ConfirmVariant;
}

export const MIDDLE_BUTTON = 1;

export async function confirmChoice(options: ConfirmChoiceOptions | ConfirmOkOptions): Promise<ConfirmChoice> {
    const answer = await openModal<'ok' | 'alt', ModalProps>(ConfirmOkModal, {
        title: options.title,
        message: options.message,
        details: options.details ?? '',
        okLabel: options.okLabel ?? t('confirm_ok.ok'),
        cancelLabel: options.cancelLabel ?? t('confirm_ok.cancel'),
        altLabel: 'altLabel' in options ? options.altLabel : '',
        variant: options.variant ?? 'plain',
    });
    return answer ?? 'cancel';
}

export async function confirmOk(options: ConfirmOkOptions): Promise<boolean> {
    return (await confirmChoice(options)) === 'ok';
}

export function confirmPositional(
    title: string,
    message: string,
    details: string | null = null,
    primaryLabel = t('confirm_ok.confirm'),
    secondaryLabel = t('confirm_ok.cancel'),
    variant: string = 'primary',
): Promise<boolean> {
    return confirmOk({
        title,
        message,
        details,
        okLabel: primaryLabel,
        cancelLabel: secondaryLabel,
        variant: variant === 'danger' ? 'danger' : 'plain',
    });
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
