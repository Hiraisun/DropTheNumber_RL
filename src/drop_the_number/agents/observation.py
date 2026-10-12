"""Public game information only. Shared by training and browser inference."""

OBSERVATION_ID = "exponents-v1"
OBSERVATION_SIZE = 34
RELATIONS_ID = "relations-v2"
OBSERVATION_SIZES = {OBSERVATION_ID: OBSERVATION_SIZE, RELATIONS_ID: 178}


def exponent(value):
    return value.bit_length() - 1 if value else 0


def observation(game, kind=OBSERVATION_ID):
    if kind not in OBSERVATION_SIZES:
        raise ValueError("対応していない観測形式です。")
    values = [exponent(n) for row in game.board for n in row]
    values.extend(exponent(n) for n in (
        game.current, game.next, game.merged_max, game.candidates()[-1]))
    # Power-of-two scaling is exact in float32; no clipping of large tiles.
    values = [n / 32 for n in values]
    if kind == RELATIONS_ID:
        cells = [n for row in game.board for n in row]
        values.extend(float(bool(n)) for n in cells)
        values.extend(float(n == game.current) for n in cells)
        values.extend(float(n == game.next) for n in cells)
        # Empty cells are not matching blocks. Only orthogonal edges are encoded.
        values.extend(float(bool(row[c]) and row[c] == row[c + 1]) for row in game.board for c in range(4))
        values.extend(float(bool(game.board[r][c]) and game.board[r][c] == game.board[r + 1][c]) for r in range(5) for c in range(5))
        values.extend(sum(bool(row[c]) for row in game.board) / 6 for c in range(5))
    return values


def board_potential(game):
    """Bounded visible-board potential; terminal states have zero potential."""
    if game.over:
        return 0.0
    heights = [sum(bool(row[c]) for row in game.board) for c in range(5)]
    roughness = sum(abs(a - b) for a, b in zip(heights, heights[1:]))
    return .5 * (1 - sum(heights) / 30) + .3 * (1 - max(heights) / 6) + .2 * (1 - roughness / 24)
