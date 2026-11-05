export function countdownText(seconds: number, t: (key: string, params?: Record<string, unknown> | null) => string): string {
    const minutes = Math.ceil(Math.max(seconds, 0) / 60);
    return minutes <= 1 ? t('pack_knock.under_minute') : t('pack_knock.minutes', { n: minutes });
}
