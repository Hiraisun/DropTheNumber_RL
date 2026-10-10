"""Public game information only. Shared by training and browser inference."""

OBSERVATION_ID = "exponents-v1"
OBSERVATION_SIZE = 34


def exponent(value):
    return value.bit_length() - 1 if value else 0


def observation(game):
    values = [exponent(n) for row in game.board for n in row]
    values.extend(exponent(n) for n in (
        game.current, game.next, game.merged_max, game.candidates()[-1]))
    # Power-of-two scaling is exact in float32; no clipping of large tiles.
    return [n / 32 for n in values]
