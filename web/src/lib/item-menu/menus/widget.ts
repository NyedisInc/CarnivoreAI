import { buildWidgetMenu } from '../../widget-menu/model';
import { defineItemMenu } from '../registry';

defineItemMenu('widget', {
    build(ctx) {
        return { nodes: buildWidgetMenu(ctx), ariaLabel: '' };
    },
});
