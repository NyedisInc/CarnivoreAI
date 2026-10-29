import { companyList } from '../companies';
import { projectColorVar } from '../project-colors/palette';
import { projectColorOf } from '../project-colors/store.svelte';
import { BAND_PROJECT_PREFIX } from '../drawer/group-store';

export const COMPANY_TINT_LIGHTNESS = 0.74;
export const COMPANY_TINT_CHROMA = 0.09;

export function projectTint(key: string): string | undefined {
    if (!key.startsWith(BAND_PROJECT_PREFIX)) return undefined;
    const id = Number(key.slice(BAND_PROJECT_PREFIX.length));
    if (!Number.isInteger(id)) return undefined;
    const color = projectColorOf(id);
    return color ? projectColorVar(color) : undefined;
}

export function companyTint(companyId: number | null): string | undefined {
    if (companyId === null) return undefined;
    const hue = companyList().find((c) => c.id === companyId)?.hue;
    return typeof hue === 'number' && Number.isFinite(hue) ? `oklch(${COMPANY_TINT_LIGHTNESS} ${COMPANY_TINT_CHROMA} ${hue})` : undefined;
}
