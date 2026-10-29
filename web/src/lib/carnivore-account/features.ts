import gates from '../../../../src/api/account_gates.json';

export type AccountFeature = keyof typeof gates;

export const ACCOUNT_FEATURES = Object.keys(gates) as AccountFeature[];

export type FunnelSource = string;

export function isGuestOk(feature: string): boolean {
    const gate = (gates as Record<string, { guest_ok?: boolean }>)[feature];
    return gate?.guest_ok === true;
}
