import json
from copy import deepcopy

import pytest

from drop_the_number import __version__
from drop_the_number.core import Game
from drop_the_number.agents.baselines import GreedyAgent, RandomAgent
from drop_the_number.agents.observation import observation, OBSERVATION_ID
from drop_the_number.agents.policy import Policy, POLICY_SCHEMA
from drop_the_number.agents.evaluation import episode
from drop_the_number.replay import reconstruct


def tiny_policy():
    return {"schema": POLICY_SCHEMA, "engine": __version__, "rules": Game(1).snapshot()["rules"],
            "observation": OBSERVATION_ID, "layers": [
                {"weights": [[(r - c) / 64 for c in range(34)] for r in range(5)],
                 "biases": [0, .1, -.2, .3, -.4], "activation": "linear"}]}


def test_observation_and_agents_ignore_hidden_state_and_do_not_mutate():
    first, other = Game(1), Game(2)
    other.board = deepcopy(first.board)
    other.current, other.next, other.merged_max = first.current, first.next, first.merged_max
    other.score = 999999
    assert observation(first) == observation(other)
    for agent in (GreedyAgent(), Policy(tiny_policy())):
        before = first.snapshot()
        assert agent.choose(first) == agent.choose(other)
        assert first.snapshot() == before
    assert len(observation(first)) == 34


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
