import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("gymnasium")
from drop_the_number.core import Game
from drop_the_number.env import DropNumberEnv
from drop_the_number.agents.observation import observation, OBSERVATION_ID, RELATIONS_ID, board_potential


def test_gym_api_seed_and_invalid_action():
    from stable_baselines3.common.env_checker import check_env
    env = DropNumberEnv()
    check_env(env)
    a, _ = env.reset(seed=123)
    b, _ = env.reset(seed=123)
    np.testing.assert_array_equal(a, b)
    before = env.game.snapshot()
    for action in (-1, 5, 1.5, True):
        with pytest.raises(ValueError): env.step(action)
    assert env.game.snapshot() == before
    env.step(np.int64(2))


@pytest.mark.parametrize("path", sorted((Path(__file__).parent / "fixtures").rglob("*.json")), ids=lambda p: p.stem)
def test_env_uses_exact_engine_transitions(path):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    env = DropNumberEnv()
    env.reset(options={"snapshot": fixture["initial"]})
    game = Game.from_snapshot(fixture["initial"])
    result = game.step(fixture["column"])
    obs, _, terminated, truncated, info = env.step(fixture["column"])
    assert env.game.snapshot() == result["state"]
    np.testing.assert_array_equal(obs, observation(game))
    assert terminated == game.over and not truncated
    assert not info["auto_drop"]


def test_time_limit_is_not_a_terminal_loss():
    env = DropNumberEnv(max_steps=1)
    env.reset(seed=1)
    _, _, terminated, truncated, _ = env.step(2)
    assert truncated and not terminated and not env.game.over
    with pytest.raises(RuntimeError): env.step(1)


@pytest.mark.parametrize("kind", [OBSERVATION_ID, RELATIONS_ID])
def test_torch_actor_matches_portable_export_on_live_states(kind):
    import torch
    from stable_baselines3 import PPO
    from drop_the_number.agents.training import export_actor
    from drop_the_number.agents.policy import Policy
    from drop_the_number.agents.baselines import GreedyAgent
    torch.set_num_threads(1)
    env = DropNumberEnv(max_steps=100, observation_id=kind)
    model = PPO("MlpPolicy", env, seed=4, n_steps=32, batch_size=32, n_epochs=1,
                policy_kwargs={"net_arch": {"pi": [16, 16], "vf": [16, 16]}, "activation_fn": torch.nn.Tanh})
    model.learn(128)
    portable = Policy(export_actor(model, {"config":{"observation":kind}}))
    game = Game(765)
    for _ in range(40):
        obs = np.asarray(observation(game, kind), dtype=np.float32)
        with torch.no_grad():
            features = model.policy.extract_features(torch.as_tensor(obs[None, :]))
            latent, _ = model.policy.mlp_extractor(features)
            logits = model.policy.action_net(latent).numpy()[0]
        np.testing.assert_allclose(portable.logits(game), logits, rtol=1e-5, atol=1e-6)
        action, _ = model.predict(obs, deterministic=True)
        assert portable.choose(game) == int(action)
        game.step(GreedyAgent().choose(game))
        if game.over: break


def test_potential_shaping_preserves_discounted_objective_and_exact_gameplay():
    from drop_the_number.agents.baselines import GreedyAgent
    gamma, coefficient = .995, .2
    base = DropNumberEnv(reward="score")
    shaped = DropNumberEnv(reward="score_potential", observation_id=RELATIONS_ID, gamma=gamma, shaping_coef=coefficient)
    base.reset(seed=789);shaped.reset(seed=789)
    difference, discount = 0.0, 1.0
    initial = board_potential(base.game)
    while not base.finished:
        action=GreedyAgent().choose(base.game)
        _, a, terminated, truncated, _ = base.step(action)
        _, b, _, _, _ = shaped.step(action)
        assert base.game.snapshot() == shaped.game.snapshot()
        difference += discount * (b-a);discount *= gamma
    assert terminated and not truncated
    assert difference == pytest.approx(-coefficient * initial)
    assert board_potential(shaped.game) == 0
    timeout = DropNumberEnv(max_steps=1,reward="score_potential",observation_id=RELATIONS_ID)
    timeout.reset(seed=1)
    _, reward, terminated, truncated, info = timeout.step(2)
    assert truncated and not terminated and board_potential(timeout.game) > 0
    assert reward == pytest.approx(info["score_delta"]/256 + coefficient * (gamma*board_potential(timeout.game)-1))
