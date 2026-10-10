import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("gymnasium")
from drop_the_number.core import Game
from drop_the_number.env import DropNumberEnv
from drop_the_number.agents.observation import observation


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


def test_torch_actor_matches_portable_export_on_live_states():
    import torch
    from stable_baselines3 import PPO
    from drop_the_number.agents.training import export_actor
    from drop_the_number.agents.policy import Policy
    from drop_the_number.agents.baselines import GreedyAgent
    torch.set_num_threads(1)
    env = DropNumberEnv(max_steps=100)
    model = PPO("MlpPolicy", env, seed=4, n_steps=32, batch_size=32, n_epochs=1,
                policy_kwargs={"net_arch": {"pi": [16, 16], "vf": [16, 16]}, "activation_fn": torch.nn.Tanh})
    model.learn(128)
    portable = Policy(export_actor(model))
    game = Game(765)
    for _ in range(40):
        obs = np.asarray(observation(game), dtype=np.float32)
        with torch.no_grad():
            features = model.policy.extract_features(torch.as_tensor(obs[None, :]))
            latent, _ = model.policy.mlp_extractor(features)
            logits = model.policy.action_net(latent).numpy()[0]
        np.testing.assert_allclose(portable.logits(game), logits, rtol=1e-5, atol=1e-6)
        action, _ = model.predict(obs, deterministic=True)
        assert portable.choose(game) == int(action)
        game.step(GreedyAgent().choose(game))
        if game.over: break
