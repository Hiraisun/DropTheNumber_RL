import json
from pathlib import Path

import pytest

from drop_the_number.core import Game
from drop_the_number.replay import new_session, reconstruct

FIXTURES = sorted((Path(__file__).parent / "fixtures").rglob("*.json"))


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_evidence_result(path):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    result = Game.from_snapshot(fixture["initial"]).step(fixture["column"])
    for key, expected in fixture["expected"].items():
        if key == "merge_results":
            actual = [event["result"] for event in result["events"] if event["kind"] == "merge"]
        elif key == "score_delta":
            actual = result[key]
        else:
            actual = result["state"][key]
        assert actual == expected


def test_diagonal_does_not_merge():
    data = Game(1).snapshot()
    data["board"][-1] = ["16", "4", "0", "0", "0"]
    data["current"] = "16"
    game = Game.from_snapshot(data)
    result = game.step(1)
    assert result["score_delta"] == "0"
    assert game.board[-2][1] == 16
    assert game.board[-1][:2] == [16, 4]


def test_generation_uses_history_and_caps_at_128():
    game = Game(123)
    assert game.candidates() == [2, 4]  # Explicit prototype initial assumption.
    game.merged_max = 16
    assert game.candidates() == [2, 4, 8]
    game.merged_max = 128
    assert game.candidates()[-1] == 64
    game.merged_max = 256
    assert game.candidates() == [2, 4, 8, 16, 32, 64, 128]
    game.merged_max = 1 << 80
    assert game.candidates()[-1] == 128
    assert game.board == [[0] * 5 for _ in range(6)]


def test_short_fixed_sequence_rolls_back_turn():
    game = Game(1, sequence=[4, 2])
    before = game.snapshot()
    with pytest.raises(ValueError, match="固定生成列"):
        game.step(2)
    assert game.snapshot() == before


def test_invalid_action_does_not_consume_random_or_preview():
    game = Game(1)
    before = game.snapshot()
    for column in (-1, 5, 1.5, True):
        assert not game.step(column)["accepted"]
    assert game.snapshot() == before


def test_replay_save_restores_full_state_and_next_random_draw():
    game = Game(765)
    session = new_session(game)
    for column in [1, 2, 1, 3, 2, 0, 4, 1, 2]:
        result = game.step(column)
        assert result["accepted"]
        session["actions"].append({"column": column})
    session["final"] = game.snapshot()
    saved = json.loads(json.dumps(session))
    restored, _ = reconstruct(saved)
    assert restored.snapshot() == game.snapshot()
    assert restored.step(3) == game.step(3)
    saved["final"]["score"] = "999999"
    with pytest.raises(ValueError, match="最終状態"):
        reconstruct(saved)


def test_large_values_are_exact_decimal_strings():
    value = 1 << 80
    data = Game(1).snapshot()
    data["board"][-1][0] = str(value)
    data["current"] = str(value)
    data["merged_max"] = str(value)
    result = Game.from_snapshot(data).step(0)
    assert result["state"]["board"][-1][0] == str(2 * value)
    assert result["state"]["score"] == str(2 * value)


def test_import_rejects_holes_and_inconsistent_terminal_state():
    data = Game(1).snapshot()
    data["board"][-2][0] = "4"
    with pytest.raises(ValueError, match="空洞"):
        Game.from_snapshot(data)
    data = Game(1).snapshot()
    data["over"] = True
    with pytest.raises(ValueError, match="終了状態"):
        Game.from_snapshot(data)


def test_preview_is_retained_when_generation_range_changes():
    data = Game(1).snapshot()
    data["board"][-1][0] = "128"
    data["current"] = "128"
    data["next"] = "4"
    data["merged_max"] = "128"
    result = Game.from_snapshot(data).step(0)
    assert result["state"]["merged_max"] == "256"
    assert result["state"]["current"] == "4"
    assert result["state"]["candidates"][-1] == "128"
