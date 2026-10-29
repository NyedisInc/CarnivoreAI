import { catalogAccount, followCatalogAccount, loadCatalogAccount, onCatalogAccountChange } from '../drawer-hud/catalog-account.svelte';
import { ACCOUNT_FEATURES, type AccountFeature } from './features';

export { onCatalogAccountChange as onAccountChange, loadCatalogAccount as refreshAccount };

export function isSignedIn(): boolean {
    return catalogAccount.facts?.signedIn === true;
}

export function isAccountLoaded(): boolean {
    return catalogAccount.loaded;
}

export function accountFacts() {
    return catalogAccount.facts;
}

export function isLocked(feature: AccountFeature): boolean {
    return (ACCOUNT_FEATURES as readonly string[]).includes(feature) && !isSignedIn();
}

export function startAccountStore(): () => void {
    return followCatalogAccount();
}
