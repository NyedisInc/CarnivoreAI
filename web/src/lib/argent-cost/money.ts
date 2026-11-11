export function formatMicros(micros: number | null | undefined): string {
    if (micros === null || micros === undefined || !Number.isFinite(micros)) return '-';
    const dollars = micros / 1_000_000;
    const four = dollars.toFixed(4);
    if (micros === 0 || Number(four) >= 1) return `$${dollars.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    if (Number(four) === 0) return '$0.0001';
    const [whole, frac] = four.split('.');
    return `$${whole}.${frac.replace(/0+$/, '').padEnd(2, '0')}`;
}
