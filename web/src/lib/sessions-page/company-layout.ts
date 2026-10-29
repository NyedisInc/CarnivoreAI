import type { Company } from '../companies';
import type { Translate } from '../sessions/types';
import type { LensGroup } from './lenses';

export interface CompanySection {
    readonly company: Company;
    readonly head: LensGroup;
    readonly groups: readonly LensGroup[];
}

export interface CompanyLayout {
    readonly sections: readonly CompanySection[];
    readonly loose: readonly LensGroup[];
    readonly groups: readonly LensGroup[];
}

export const COMPANY_GROUP_PREFIX = 'company:';

const localCompanyId = (g: LensGroup): number | null => (g.rows.some((r) => !!r.computer) ? null : (g.project?.company_id ?? null));

export function companyLayout(groups: readonly LensGroup[], companies: readonly Company[], find: string, withEmpties: boolean, t: Translate): CompanyLayout {
    const needle = find.trim().toLowerCase();
    const known = new Set(companies.map((c) => c.id));
    const sections: CompanySection[] = [];
    for (const company of companies) {
        const own = groups.filter((g) => localCompanyId(g) === company.id);
        if (own.length === 0 && !(withEmpties && company.name.toLowerCase().includes(needle))) continue;
        const head: LensGroup = {
            key: `${COMPANY_GROUP_PREFIX}${company.id}`,
            label: company.name,
            bits: [t('sessions.page.company.projects', { count: own.length })],
            measure: '',
            rows: [],
            count: own.length,
            live: own.reduce((n, g) => n + g.live, 0),
            project: null,
            provider: null,
        };
        sections.push({ company, head, groups: own });
    }
    const loose = groups.filter((g) => {
        const id = localCompanyId(g);
        return id === null || !known.has(id);
    });
    return { sections, loose, groups: [...sections.flatMap((s) => s.groups), ...loose] };
}
