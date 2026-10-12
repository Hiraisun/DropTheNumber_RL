import json
from copy import deepcopy

import pytest

from drop_the_number import __version__
from drop_the_number.core import Game
from drop_the_number.agents.baselines import GreedyAgent, RandomAgent
from drop_the_number.agents.observation import observation, OBSERVATION_ID, RELATIONS_ID, OBSERVATION_SIZES
from drop_the_number.agents.policy import Policy, POLICY_SCHEMA
from drop_the_number.agents.evaluation import episode
from drop_the_number.replay import reconstruct


def tiny_policy():
    return {"schema": POLICY_SCHEMA, "engine": __version__, "rules": Game(1).snapshot()["rules"],
            "observation": OBSERVATION_ID, "layers": [
                {"weights": [[(r - c) / 64 for c in range(34)] for r in range(5)],
                 "biases": [0, .1, -.2, .3, -.4], "activation": "linear"}]}


@pytest.mark.parametrize("kind", [OBSERVATION_ID, RELATIONS_ID])
def test_observation_and_agents_ignore_hidden_state_and_do_not_mutate(kind):
    first, other = Game(1), Game(2)
    other.board = deepcopy(first.board)
    other.current, other.next, other.merged_max = first.current, first.next, first.merged_max
    other.score = 999999
    assert observation(first, kind) == observation(other, kind)
    data = tiny_policy()
    data["observation"] = kind
    data["layers"][0]["weights"] = [[(r-c)/64 for c in range(OBSERVATION_SIZES[kind])] for r in range(5)]
    for agent in (GreedyAgent(), Policy(data)):
        before = first.snapshot()
        assert agent.choose(first) == agent.choose(other)
        assert first.snapshot() == before
    assert len(observation(first, kind)) == OBSERVATION_SIZES[kind]


def test_relational_observation_encodes_equal_blocks_not_empty_or_diagonal_edges():
    game = Game(1)
    game.current, game.next = 16, 32
    game.board[4] = [8,16,0,0,4]
    game.board[5] = [16,16,32,0,2]
    values = observation(game, RELATIONS_ID)
    assert values[89] == 1 and values[121] == 1
    assert values[144:148] == [1,0,0,0]
    assert values[169] == 1
    assert sum(values[124:148]) == 1 and sum(values[148:173]) == 1
    assert values[173:] == [2/6,2/6,1/6,0,2/6]


def test_score_target_rate_and_lower_decile_use_all_games():
    from drop_the_number.agents.evaluation import summarize
    rows=[{"score":str(n),"moves":20,"merged_max":"512","truncated":False,"inference_ms_per_move":1} for n in (1000,15000,20000)]
    result=summarize(rows)
    assert result["score_15000_rate"] == pytest.approx(2/3)
    assert result["score_p10"] == pytest.approx(3800)
    assert summarize([])["score_15000_rate"] is None


def test_bad_policy_weights_and_dimensions_are_rejected():
    for mutation in ("nan", "size", "rules", "output"):
        data = tiny_policy()
        if mutation == "nan": data["layers"][0]["weights"][0][0] = float("nan")
        if mutation == "size": data["layers"][0]["weights"][0].pop()
        if mutation == "rules": data["rules"]["id"] = "prototype-v1"
        if mutation == "output": data["layers"][0]["biases"].pop()
        with pytest.raises(ValueError): Policy(data)


def test_policy_rejects_game_with_different_generation_rules():
    from drop_the_number.core import Rules
    game = Game(1, rules=Rules(spawn_cap=64))
    with pytest.raises(ValueError, match="ルール"):
        Policy(tiny_policy()).choose(game)


def test_bridge_policy_load_is_atomic_and_ai_choice_does_not_advance_game():
    from drop_the_number.bridge import dispatch
    def call(**data): return json.loads(dispatch(json.dumps(data)))
    call(command="new", seed=765, diagnostic=True)
    call(command="load-policy", policy=tiny_policy())
    before = call(command="export")
    choice = call(command="ai-action", agent="ppo")
    assert call(command="export") == before
    data = tiny_policy()
    data["layers"][0]["weights"][0].pop()
    with pytest.raises(ValueError): call(command="load-policy", policy=data)
    assert call(command="ai-action", agent="ppo") == choice
    assert call(command="export") == before


@pytest.mark.parametrize("agent", [GreedyAgent(), RandomAgent(4), Policy(tiny_policy())])
def test_ai_records_reconstruct_exactly(agent):
    metrics, session = episode(agent, 765, max_steps=50)
    session = json.loads(json.dumps(session))
    restored, _ = reconstruct(session)
    assert restored.snapshot() == session["final"]
    assert metrics["moves"] == len(session["actions"])
    assert session["diagnostic"] and not session["settings"]["auto_drop"]
    assert all(a["source"] == "ai" for a in session["actions"])
