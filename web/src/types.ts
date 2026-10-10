export type Board = string[][];
export interface Snapshot {
  engine: string; rules: { id: string; columns: number; rows: number };
  board: Board; score: string; current: string; next: string; merged_max: string;
  moves: number; over: boolean; seed: number; candidates: string[];
}
export interface MoveEvent {
  kind: 'drop' | 'merge' | 'gravity' | 'over'; board: Board; score: string;
  value?: string; result?: string; count?: number; at?: [number, number];
  from?: [number, number]; to?: [number, number];
  sources?: [number, number][];
  movements?: { value: string; from: [number, number]; to: [number, number] }[];
}
export interface Result { state: Snapshot; events: MoveEvent[]; accepted?: boolean; reason?: string; score_delta?: string; diagnostic: boolean; settings?: { auto_drop: boolean } }
export interface Session { schema: string; initial: Snapshot; final?: Snapshot; actions: { column: number; source?: string; elapsed_ms?: number }[]; settings: { auto_drop: boolean; interval_ms: number }; diagnostic: boolean; generated?: string[] }
