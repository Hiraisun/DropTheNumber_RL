export class EngineClient {
  private worker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' });
  private nextId = 0;
  private pending = new Map<number, { resolve: (value: unknown) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }>();

  constructor(progress: (text: string) => void) {
    this.worker.onmessage = ({ data }) => {
      if (data.progress) { progress(data.progress); return; }
      const pending = this.pending.get(data.id);
      if (!pending) return;
      clearTimeout(pending.timer);
      this.pending.delete(data.id);
      if (data.error) pending.reject(new Error(data.error));
      else pending.resolve(data.result);
    };
    this.worker.onerror = () => this.rejectAll(new Error('ゲームエンジンの実行に失敗しました。再読み込みしてください。'));
  }

  request<T>(payload: Record<string, unknown>): Promise<T> {
    const id = ++this.nextId;
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('エンジンから応答がありません。再読み込みしてください。')); }, payload.command === 'boot' ? 120000 : 15000);
      this.pending.set(id, { resolve: value => resolve(value as T), reject, timer });
      this.worker.postMessage({ id, payload });
    });
  }

  private rejectAll(error: Error) { for (const p of this.pending.values()) { clearTimeout(p.timer); p.reject(error); } this.pending.clear(); }
  destroy() { this.worker.terminate(); this.rejectAll(new Error('エンジンを再起動しました。')); }
}
