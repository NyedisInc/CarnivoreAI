import type { MenuNode } from '../../drawer-tabs/add-component-menu';
import { BROWSER_PREFIX } from '../../drawer/browser-rows';
import { pageById } from '../../browser/pages.svelte';
import { pageRowActions } from '../../../cplugs/sdk/page-row-actions';
import { contributeItemMenu } from '../registry';

contributeItemMenu('page', {
    id: 'plugin-page-row-actions',
    nodes(ctx): MenuNode[] {
        const page = ctx.name.startsWith(BROWSER_PREFIX) ? pageById(ctx.name.slice(BROWSER_PREFIX.length)) : null;
        if (!page) return [];
        const out: MenuNode[] = [];
        for (const action of pageRowActions()) {
            try {
                const target = action.targetOf({ key: page.key, src: page.src, title: page.title });
                if (target !== null) out.push({ id: action.id, label: action.label(), run: () => action.run(target) });
            } catch (error) {
                console.error(`[item-menu] page row action "${action.id}" of plugin "${action.plugin}" failed and was skipped:`, error);
            }
        }
        return out;
    },
});
