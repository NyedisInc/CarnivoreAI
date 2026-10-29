import { openModal } from '../modal';
import RegisterModal from './RegisterModal.svelte';

let open = false;

export async function openRegisterModal(): Promise<void> {
    if (open) return;
    open = true;
    try {
        await openModal<'registered', Record<string, unknown>>(RegisterModal as never, {});
    } finally {
        open = false;
    }
}
