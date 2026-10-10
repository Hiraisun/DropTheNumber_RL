"""Turn-based puzzle engine. No renderer, wall clock, or runtime dependencies."""

from copy import deepcopy
from dataclasses import asdict, dataclass

from drop_the_number import __version__

SCHEMA = "drop-number/session-v1"
MAX_IMPORT_MOVES = 10000


def tile(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("ブロックは整数または10進文字列で指定してください。")
    n = int(value)
    if n < 2 or n & (n - 1) or n.bit_length() > 1024:
        raise ValueError("ブロックは2以上の2の累乗で指定してください（最大1024ビット）。")
    return n


@dataclass(frozen=True)
class Rules:
    id: str = "prototype-v1"
    columns: int = 5
    rows: int = 6  # Row 0 is the terminal line, checked after resolving merges.
    initial_spawn_max: int = 4
    spawn_min: int = 2
    spawn_cap: int = 128
    cleanup: str = "none-unverified"

    def __post_init__(self):
        if self.id != "prototype-v1" or self.columns != 5 or self.rows != 6:
            raise ValueError("この版はprototype-v1の5列×6段だけに対応しています。")
        for value in (self.initial_spawn_max, self.spawn_min, self.spawn_cap):
            tile(value)
        if not self.spawn_min <= self.initial_spawn_max <= self.spawn_cap:
            raise ValueError("生成値の下限・初期上限・上限が不正です。")
        if self.cleanup != "none-unverified":
            raise ValueError("進行消去は未確認のため、この版では無効です。")


class Game:
    def __init__(self, seed=1, rules=None, sequence=None):
        self.rules = rules or Rules()
        if type(seed) is not int or not 0 <= seed <= 0xFFFFFFFF:
            raise ValueError("seedは0～4294967295の整数で指定してください。")
        self.seed = seed
        self.rng = seed or 0x6D2B79F5
        self.sequence = None if sequence is None else [tile(v) for v in sequence]
        self.sequence_index = 0
        self.generated = []
        self.board = [[0] * self.rules.columns for _ in range(self.rules.rows)]
        self.score = 0
        self.merged_max = 0
        self.moves = 0
        self.over = False
        self.current = self._draw()
        self.next = self._draw()

    def _randbelow(self, count):
        # Explicit 32-bit PRNG + rejection sampling: identical in both runtimes.
        while True:
            x = self.rng
            x ^= (x << 13) & 0xFFFFFFFF
            x ^= x >> 17
            x ^= (x << 5) & 0xFFFFFFFF
            self.rng = x & 0xFFFFFFFF
            value = self.rng - 1  # Nonzero xorshift state has 2**32 - 1 values.
            # Correct the rejection interval for the nonzero state space.
            limit = 0xFFFFFFFF - (0xFFFFFFFF % count)
            if value < limit:
                return value % count

    def candidates(self):
        maximum = max(self.rules.initial_spawn_max,
                      min(self.merged_max // 2, self.rules.spawn_cap))
        values = []
        n = self.rules.spawn_min
        while n <= maximum:
            values.append(n)
            n *= 2
        return values

    def _draw(self):
        if self.sequence is not None:
            if self.sequence_index >= len(self.sequence):
                raise ValueError("固定生成列が足りません。次の予告分も追加してください。")
            value = self.sequence[self.sequence_index]
            self.sequence_index += 1
        else:
            values = self.candidates()
            value = values[self._randbelow(len(values))]
        self.generated.append(str(value))
        return value

    def _wire_board(self):
        return [[str(n) for n in row] for row in self.board]

    def snapshot(self):
        return {
            "engine": __version__, "rules": asdict(self.rules), "seed": self.seed,
            "board": self._wire_board(), "score": str(self.score),
            "current": str(self.current), "next": str(self.next),
            "merged_max": str(self.merged_max), "moves": self.moves,
            "over": self.over, "rng": self.rng,
            "sequence": None if self.sequence is None else [str(n) for n in self.sequence],
            "sequence_index": self.sequence_index, "generated": self.generated.copy(),
            "candidates": [str(n) for n in self.candidates()],
        }

    @classmethod
    def from_snapshot(cls, data):
        if data.get("engine", __version__) != __version__:
            raise ValueError("対応していないエンジン版です。")
        rules = Rules(**data.get("rules", {}))
        board = data["board"]
        if len(board) != rules.rows or any(len(row) != rules.columns for row in board):
            raise ValueError("盤面は上から下へ6行、各行5列で指定してください。")
        parsed = []
        for row in board:
            parsed.append([0 if (type(v) is int and v == 0) or (type(v) is str and v == "0") else tile(v) for v in row])
        for col in range(rules.columns):
            seen = False
            for row in parsed:
                if row[col]:
                    seen = True
                elif seen:
                    raise ValueError("初期盤面の各列は下に詰めてください。空洞は読み込めません。")
        game = cls.__new__(cls)
        game.rules = rules
        game.seed = data.get("seed", 1)
        game.rng = data.get("rng", game.seed or 0x6D2B79F5)
        if type(game.seed) is not int or not 0 <= game.seed <= 0xFFFFFFFF:
            raise ValueError("seedが不正です。")
        if type(game.rng) is not int or not 1 <= game.rng <= 0xFFFFFFFF:
            raise ValueError("乱数状態が不正です。")
        game.board = parsed
        game.current = tile(data["current"])
        game.next = tile(data["next"])
        game.score = int(data.get("score", "0"))
        game.merged_max = int(data.get("merged_max", "0"))
        game.moves = data.get("moves", 0)
        if game.score < 0 or game.score.bit_length() > 2048 or type(game.moves) is not int or not 0 <= game.moves <= MAX_IMPORT_MOVES:
            raise ValueError("得点または手数が不正です。")
        if game.merged_max:
            tile(game.merged_max)
        game.over = data.get("over", any(parsed[0]))
        if type(game.over) is not bool or game.over != bool(any(parsed[0])):
            raise ValueError("終了状態と最上段の占有が一致しません。")
        game.sequence = data.get("sequence")
        if game.sequence is not None:
            if len(game.sequence) > MAX_IMPORT_MOVES + 2:
                raise ValueError("固定生成列が長すぎます。")
            game.sequence = [tile(n) for n in game.sequence]
        game.sequence_index = data.get("sequence_index", 0)
        if type(game.sequence_index) is not int or game.sequence_index < 0 or (game.sequence is not None and game.sequence_index > len(game.sequence)):
            raise ValueError("固定生成列の位置が不正です。")
        generated = data.get("generated", [])
        if len(generated) > MAX_IMPORT_MOVES + 2:
            raise ValueError("生成記録が長すぎます。")
        game.generated = [str(tile(n)) for n in generated]
        return game

    def step(self, column):
        if self.over:
            return {"accepted": False, "reason": "ゲームは終了しています。", "events": [], "state": self.snapshot()}
        if type(column) is not int or not 0 <= column < self.rules.columns:
            return {"accepted": False, "reason": "列は0～4で指定してください。", "events": [], "state": self.snapshot()}
        if self.board[0][column]:
            return {"accepted": False, "reason": "この列には設置できません。", "events": [], "state": self.snapshot()}
        previous = deepcopy(self.__dict__)
        try:
            return self._step(column)
        except Exception:
            self.__dict__ = previous  # A short fixed sequence must not partially mutate a turn.
            raise

    def _step(self, column):
        events = []
        before_score = self.score
        row = self.rules.rows - 1
        while self.board[row][column]:
            row -= 1
        self.board[row][column] = self.current
        events.append({"kind": "drop", "value": str(self.current), "from": [-1, column],
                       "to": [row, column], "board": self._wire_board(), "score": str(self.score)})
        while True:
            value = self.board[row][column]
            targets = [(r, c) for r, c in ((row + 1, column), (row, column - 1), (row, column + 1))
                       if 0 <= r < self.rules.rows and 0 <= c < self.rules.columns and self.board[r][c] == value]
            if not targets:
                break
            result = value << len(targets)
            for r, c in targets:
                self.board[r][c] = 0
            self.board[row][column] = result
            self.score += result
            self.merged_max = max(self.merged_max, result)
            events.append({"kind": "merge", "value": str(value), "result": str(result),
                           "count": len(targets) + 1, "at": [row, column],
                           "sources": [list(p) for p in targets],
                           "board": self._wire_board(), "score": str(self.score)})
            movements = []
            active_row = row
            for col in range(self.rules.columns):
                occupied = [(r, self.board[r][col]) for r in range(self.rules.rows) if self.board[r][col]]
                self.board_col_clear(col)
                first = self.rules.rows - len(occupied)
                for offset, (old_row, n) in enumerate(occupied):
                    new_row = first + offset
                    self.board[new_row][col] = n
                    if col == column and old_row == row:
                        active_row = new_row
                    if new_row != old_row:
                        movements.append({"value": str(n), "from": [old_row, col], "to": [new_row, col]})
            row = active_row
            if movements:
                events.append({"kind": "gravity", "movements": movements,
                               "board": self._wire_board(), "score": str(self.score)})
        self.moves += 1
        self.over = bool(any(self.board[0]))
        if self.over:
            events.append({"kind": "over", "reason": "ceiling", "board": self._wire_board(), "score": str(self.score)})
        else:
            self.current = self.next
            self.next = self._draw()  # Already-visible preview is retained across a milestone.
        return {"accepted": True, "events": events, "score_delta": str(self.score - before_score), "state": self.snapshot()}

    def board_col_clear(self, column):
        for row in self.board:
            row[column] = 0
