import { closing } from '../../widget-menu/model';
import { defineItemMenu } from '../registry';

defineItemMenu('pagerow', {
    build(ctx, env) {
        if (ctx.nodes.length === 0) return null;
        return { nodes: closing(ctx.nodes, env.close), ariaLabel: ctx.label };
    },
});
