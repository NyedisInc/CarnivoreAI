/* gives the same */
import { displayKind } from '../catalog/kind-display';

export const HERO_W = 1536;
export const HERO_H = 1024;

export interface HeroColors { ground: string; kind: string; line: string }

type ArtKind = 'skill' | 'theme' | 'mod' | 'plugin';

function hash(text: string): number {
    let h = 2166136261;
    for (let i = 0; i < text.length; i++) {
        h ^= text.charCodeAt(i);
        h = Math.imul(h, 16777619);
    }
    return h >>> 0;
}

/* gives the same */
function rng(seed: number): () => number {
    let a = seed;
    return () => {
        a |= 0;
        a = (a + 0x6d2b79f5) | 0;
        let t = Math.imul(a ^ (a >>> 15), 1 | a);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

function artKind(kind: string): ArtKind {
    const shown = displayKind(kind);
    return shown === 'theme' || shown === 'mod' || shown === 'plugin' ? shown : 'skill';
}

export function heroSvg(seed: string, kind: string, colors: HeroColors): string {
    const k = artKind(kind);
    const next = rng(hash(`${seed}|${k}`));
    const n = (a: number, b: number): number => a + (b - a) * next();
    const id = `g${hash(seed)}`;
    const { ground, kind: tint, line } = colors;
    const o: string[] = [];
    o.push(`<rect width="${HERO_W}" height="${HERO_H}" fill="${ground}"/>`);
    o.push(`<defs><linearGradient id="${id}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${tint}" stop-opacity=".22"/><stop offset="1" stop-color="${tint}" stop-opacity="0"/></linearGradient></defs>`);
    o.push(`<rect width="${HERO_W}" height="${HERO_H}" fill="url(#${id})"/>`);
    for (let i = 1; i < 12; i++) o.push(`<path d="M${i * 128} 0V${HERO_H}" stroke="${line}" stroke-width="1" opacity=".35"/>`);
    for (let i = 1; i < 8; i++) o.push(`<path d="M0 ${i * 128}H${HERO_W}" stroke="${line}" stroke-width="1" opacity=".35"/>`);
    const cx = n(600, 936);
    const cy = n(380, 640);
    if (k === 'theme') {
        for (let i = 0; i < 7; i++) {
            const w = n(90, 200);
            o.push(`<rect x="${cx - 420 + i * 125}" y="${cy - 260 + n(-60, 60)}" width="${w * 0.6}" height="${n(300, 560)}" fill="${tint}" opacity="${n(0.18, 0.8).toFixed(2)}"/>`);
        }
    } else if (k === 'mod') {
        for (let i = 0; i < 9; i++) {
            const s = n(80, 260);
            o.push(`<rect x="${n(260, 1180)}" y="${n(160, 780)}" width="${s}" height="${s}" fill="none" stroke="${tint}" stroke-width="${n(3, 10)}" opacity="${n(0.3, 0.9).toFixed(2)}"/>`);
        }
        o.push(`<circle cx="${cx}" cy="${cy}" r="${n(120, 210)}" fill="${tint}" opacity=".22"/><circle cx="${cx}" cy="${cy}" r="${n(40, 80)}" fill="${ground}"/>`);
    } else if (k === 'plugin') {
        for (let i = 0; i < 6; i++) {
            const y = n(180, 840);
            const x0 = n(200, 700);
            o.push(`<path d="M${x0} ${y}H${x0 + n(300, 700)}v${n(-120, 120)}h${n(100, 260)}" fill="none" stroke="${tint}" stroke-width="${n(4, 12)}" opacity="${n(0.3, 0.85).toFixed(2)}"/>`);
            o.push(`<circle cx="${x0}" cy="${y}" r="${n(14, 34)}" fill="${tint}"/>`);
        }
    } else {
        for (let i = 0; i < 5; i++) {
            const dy = i * n(70, 110);
            o.push(`<path d="M${cx} ${cy - 220 + dy} ${cx + 360} ${cy - 60 + dy} ${cx} ${cy + 100 + dy} ${cx - 360} ${cy - 60 + dy}Z" fill="${tint}" opacity="${(0.12 + i * 0.1).toFixed(2)}" stroke="${tint}" stroke-width="3"/>`);
        }
    }
    for (let i = 0; i < 40; i++) {
        o.push(`<circle cx="${n(0, HERO_W).toFixed(0)}" cy="${n(0, HERO_H).toFixed(0)}" r="${n(2, 7).toFixed(1)}" fill="${tint}" opacity="${n(0.15, 0.6).toFixed(2)}"/>`);
    }
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${HERO_W} ${HERO_H}" width="${HERO_W}" height="${HERO_H}">${o.join('')}</svg>`;
}

export function heroSeed(name: string, kind: string): string {
    return `${name}@${kind}`;
}

export function heroColors(kind: string, root: HTMLElement = document.documentElement): HeroColors {
    const probe = document.createElement('span');
    probe.style.display = 'none';
    root.appendChild(probe);
    try {
        const read = (token: string): string => {
            probe.style.color = '';
            probe.style.color = `var(${token})`;
            return getComputedStyle(probe).color;
        };
        return { ground: read('--oc-ground-page'), kind: read(`--oc-kind-${artKind(kind)}`), line: read('--oc-line-rule') };
    } finally {
        probe.remove();
    }
}
