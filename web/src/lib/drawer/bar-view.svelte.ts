import type { AccountIdentity } from '../drawer-hud/account-identity';

export interface VersionView {
    text: string;
    preview: boolean;
    previewText: string;
    href: string | null;
}

export interface BarView {
    crown: boolean;
    version: VersionView | null;
    /* the account chip */
    identity?: AccountIdentity | null;
}

export const barView: BarView = $state({ crown: false, version: null });
