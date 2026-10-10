import type { Board, MoveEvent } from './types';

const WIDTH = 450, HEIGHT = 650, CELL = 82, LEFT = 20, TOP = 130, SIZE = 75;
const palette = [
  '#eac9a7', '#b9d0a2', '#e9b377', '#a8cebf', '#c9c2e4',
  '#dfaec4', '#9ebfcf', '#e7d078', '#d4a080',
];
// Solid interior colors sampled from the supplied official-game screenshots.
const referencePalette: Record<string, string> = {
  '2': '#c733b2', '4': '#63e238', '8': '#44d3c5', '16': '#347acf',
  '32': '#d2463e', '64': '#8164f9', '128': '#8c7d79', '256': '#f5a22c',
  '512': '#ee3166', '1024': '#ae1910', '2048': '#bc19dc', '4096': '#3f96db',
  '8192': '#46f70e', '16384': '#d6076a', '32768': '#10d58b', '65536': '#f06107',
};

export function tileColor(value: string) {
  const fallback = palette[Math.max(0, BigInt(value).toString(2).length - 2) % palette.length];
  return [referencePalette[value] ?? fallback, '#ffffff'];
}
export function compact(value: string) { return value.length <= 6 ? value : `${value[0]}.${value.slice(1, 3)}e${value.length - 1}`; }
export function formatted(value: string) { return new Intl.NumberFormat('ja-JP').format(BigInt(value)); }

export class Renderer {
  private ctx: CanvasRenderingContext2D;
  board: Board = Array.from({ length: 6 }, () => Array<string>(5).fill('0'));
  current = '0'; selected = 2; incomingProgress = 0; showIncoming = true;
  event: MoveEvent | undefined;
  eventProgress = 1;
  constructor(private canvas: HTMLCanvasElement) {
    this.ctx = canvas.getContext('2d')!;
    const resize = () => {
      const ratio = Math.min(window.devicePixelRatio || 1, 3);
      canvas.width = WIDTH * ratio; canvas.height = HEIGHT * ratio;
      this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      this.draw();
    };
    resize();
    window.addEventListener('resize', resize);
  }

  column(clientX: number) {
    const x = (clientX - this.canvas.getBoundingClientRect().left) / this.canvas.getBoundingClientRect().width * WIDTH;
    return Math.max(0, Math.min(4, Math.floor((x - LEFT) / CELL)));
  }

  private position(row: number, column: number): [number, number] { return [LEFT + column * CELL, row === -1 ? 23 : TOP + row * CELL]; }
  private block(value: string, x: number, y: number, pulse = 0) {
    const ctx = this.ctx, [bg, ink] = tileColor(value);
    const inset = -pulse * 3;
    ctx.fillStyle = '#00000022'; ctx.beginPath(); ctx.roundRect(x + inset, y + 3 + inset, SIZE - inset * 2, SIZE - inset * 2, 10); ctx.fill();
    ctx.fillStyle = bg; ctx.beginPath(); ctx.roundRect(x + inset, y + inset, SIZE - inset * 2, SIZE - inset * 2, 10); ctx.fill();
    const label = compact(value);
    ctx.fillStyle = ink; ctx.font = `700 ${label.length > 5 ? 18 : label.length > 3 ? 23 : 31}px "Space Grotesk", Arial, sans-serif`;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(label, x + SIZE / 2, y + SIZE / 2 + 1);
  }

  draw() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, WIDTH, HEIGHT);
    ctx.fillStyle = '#26352f'; ctx.fillRect(0, 0, WIDTH, HEIGHT);
    ctx.fillStyle = '#34463b'; ctx.beginPath(); ctx.roundRect(LEFT + this.selected * CELL - 3, 15, SIZE + 6, 94, 8); ctx.fill();
    for (let c = 0; c < 5; c++) {
      const x = LEFT + c * CELL;
      ctx.fillStyle = '#64725f'; ctx.beginPath(); ctx.moveTo(x + 31, 55); ctx.lineTo(x + 44, 55); ctx.lineTo(x + 37.5, 61); ctx.fill();
      for (let r = 0; r < 6; r++) {
        ctx.fillStyle = r === 0 ? '#64473855' : c === this.selected ? '#3b4b3b' : '#314033';
        ctx.beginPath(); ctx.roundRect(x, TOP + r * CELL, SIZE, SIZE, 8); ctx.fill();
      }
    }
    ctx.strokeStyle = '#d18a6170'; ctx.setLineDash([4, 5]); ctx.beginPath(); ctx.moveTo(20, TOP - 5); ctx.lineTo(423, TOP - 5); ctx.stroke(); ctx.setLineDash([]);
    const moving = new Set<string>();
    if (this.event?.kind === 'drop' && this.event.to) moving.add(this.event.to.join(','));
    if (this.event?.kind === 'gravity') for (const m of this.event.movements!) moving.add(m.to.join(','));
    for (let r = 0; r < 6; r++) for (let c = 0; c < 5; c++) {
      if (this.board[r][c] === '0' || moving.has(`${r},${c}`)) continue;
      const pulse = this.event?.kind === 'merge' && this.event.at?.[0] === r && this.event.at?.[1] === c ? Math.sin(this.eventProgress * Math.PI) : 0;
      this.block(this.board[r][c], ...this.position(r, c), pulse);
    }
    const eased = 1 - (1 - this.eventProgress) ** 2;
    const movingBlock = (value: string, from: [number, number], to: [number, number]) => {
      const [x0, y0] = this.position(...from), [x1, y1] = this.position(...to);
      this.block(value, x0 + (x1 - x0) * eased, y0 + (y1 - y0) * eased);
    };
    if (this.event?.kind === 'drop') movingBlock(this.event.value!, this.event.from!, this.event.to!);
    if (this.event?.kind === 'gravity') for (const m of this.event.movements!) movingBlock(m.value, m.from, m.to);
    if (this.showIncoming && this.current !== '0') {
      let landing = 5;
      while (landing > 0 && this.board[landing][this.selected] !== '0') landing--;
      const [x, y] = this.position(-1, this.selected), [, target] = this.position(landing, this.selected);
      this.block(this.current, x, y + (target - y) * this.incomingProgress);
    }
  }
}
