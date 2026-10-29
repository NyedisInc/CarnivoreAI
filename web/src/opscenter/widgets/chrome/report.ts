
import { authFetch } from '../../api/auth.svelte';
import { refreshAlerts } from '../../../lib/app-alerts/alerts.svelte';
import type { FitSize, FitZone } from '../types';
import type { MisfitReason } from '../fits';

export type ReportReason = MisfitReason | 'reported';

export interface WidgetReport {
  widget: string;
  zone: FitZone;
  size: FitSize | null;
  reason: ReportReason;
}

/* could not be reached */
export async function reportWidget(report: WidgetReport): Promise<boolean> {
  try {
    await authFetch('/alerts/widget-report', {
      method: 'POST',
      body: JSON.stringify({
        widget: report.widget,
        zone: report.zone,
        w: report.size?.w ?? 0,
        h: report.size?.h ?? 0,
        reason: report.reason,
      }),
    });
  } catch (error) {
    // could not
    console.warn('widget_report_failed', { widget: report.widget, zone: report.zone, error: String(error) });
    return false;
  }
  await refreshAlerts();
  return true;
}
