import { openModal } from '../modal';
import { cancelPendingAccount, registerSignInOpener, type SignInRequest } from './funnel';
import SignInModal from './SignInModal.svelte';

export async function openSignInModal(request: SignInRequest): Promise<void> {
    const result = await openModal<'signed_in', Record<string, unknown>>(
        SignInModal as never,
        { feature: request.feature, src: request.src },
    );
    if (result !== 'signed_in') cancelPendingAccount();
}

export function installSignInModal(): void {
    registerSignInOpener((request) => void openSignInModal(request));
}
