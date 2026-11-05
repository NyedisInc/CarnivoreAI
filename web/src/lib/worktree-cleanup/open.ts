import { openModal } from '../modal';
import CleanupModal from './CleanupModal.svelte';
import type { CleanupScope } from './api';

export function openWorktreeCleanup(scope: CleanupScope): Promise<{ removed: number } | null> {
    return openModal<{ removed: number }, { scope: CleanupScope }>(CleanupModal as never, { scope });
}
