import { openModal } from '../modal';
import ShowPathModal from './ShowPathModal.svelte';

export async function showPath(path: string, name: string): Promise<void> {
    await openModal<null, { path: string; name: string }>(ShowPathModal as never, { path, name });
}
