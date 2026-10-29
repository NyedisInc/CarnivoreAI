/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { MIN_PLOT_HEIGHT_PX, chartFits, plotBoxHeight } from './plot-fit';

afterEach(() => { document.body.innerHTML = ''; });

function band(card: number, own: number, top: number): HTMLElement {
  const frame = document.createElement('section');
  const plot = document.createElement('div');
  frame.append(plot);
  document.body.append(frame);
  Object.defineProperty(frame, 'clientHeight', { configurable: true, value: card });
  Object.defineProperty(plot, 'clientHeight', { configurable: true, value: own });
  Object.defineProperty(plot, 'offsetTop', { configurable: true, value: top });
  plot.style.marginBottom = '4px';
  return plot;
}

describe('plotBoxHeight', () => {
  test('a band held at its 70px floor but overflowing the card reads as the room left, and the chart is dropped', () => {
    const room = plotBoxHeight(band(120, MIN_PLOT_HEIGHT_PX, 100));
    expect(room).toBe(16);
    expect(chartFits(room)).toBe(false);
  });

  test('a band that fits its card reads its own height and keeps the chart', () => {
    const room = plotBoxHeight(band(300, 150, 146));
    expect(room).toBe(150);
    expect(chartFits(room)).toBe(true);
  });

  test('a collapsed band reads the room under its top edge, less its margin, so the chart can come back', () => {
    expect(plotBoxHeight(band(300, 0, 200))).toBe(96);
  });
});
