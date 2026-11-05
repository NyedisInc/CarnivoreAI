import { downloadableRow } from '../../open-files/download-row.svelte';
import { downloadWithMessage } from '../../open-files/download';
import type { RowMenuCtx } from '../row-context';
import { say } from './run-env';

export async function runDownload(ctx: RowMenuCtx): Promise<void> {
    const file = downloadableRow(ctx.name);
    if (!file) return;
    const text = await downloadWithMessage(file);
    if (text) say(ctx, text);
}
