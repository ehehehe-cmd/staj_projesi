"""training/agents/networks.py + dqn_agent.py birim testleri — Faz 4."""

import torch

from app.training.agents.dqn_agent import DQNHyperparams, MaskedDQNAgent
from app.training.agents.networks import QNetwork


class TestQNetwork:
    def test_forward_shape(self):
        net = QNetwork(input_dim=6, output_dim=4, hidden_dim=16)
        out = net(torch.zeros((3, 6)))
        assert out.shape == (3, 4)

    def test_four_linear_layers(self):
        net = QNetwork(input_dim=6, output_dim=4, hidden_dim=16)
        linears = [m for m in net.net if isinstance(m, torch.nn.Linear)]
        assert len(linears) == 4


def _tiny_hp(**overrides) -> DQNHyperparams:
    base = dict(
        hidden_dim=8,
        learning_rate=1e-2,
        gamma=0.9,
        batch_size=4,
        target_update_interval=2,
        replay_capacity=100,
        min_replay_size=4,
        epsilon_start=1.0,
        epsilon_end=0.0,
        epsilon_decay_steps=10,
    )
    base.update(overrides)
    return DQNHyperparams(**base)


class TestMaskedDQNAgent:
    def test_select_action_respects_mask_greedy(self):
        agent = MaskedDQNAgent(input_dim=3, output_dim=4, hyperparams=_tiny_hp(), level="manager", seed=1)
        mask = [False, True, False, True]
        for _ in range(20):
            action = agent.select_action([0.1, 0.2, 0.3], mask, greedy=True)
            assert action in (1, 3)

    def test_select_action_respects_mask_during_exploration(self):
        agent = MaskedDQNAgent(
            input_dim=3, output_dim=4, hyperparams=_tiny_hp(epsilon_start=1.0, epsilon_end=1.0), level="worker", seed=2
        )
        mask = [True, False, False, False]
        for _ in range(20):
            action = agent.select_action([0.1, 0.2, 0.3], mask)
            assert action == 0

    def test_train_step_returns_none_before_min_replay_size(self):
        agent = MaskedDQNAgent(input_dim=2, output_dim=2, hyperparams=_tiny_hp(min_replay_size=100), level="manager", seed=3)
        agent.store([0.0, 0.0], [True, True], 0, 1.0, [0.0, 0.0], [True, True], False)
        assert agent.train_step() is None

    def test_train_step_returns_loss_after_min_replay_size(self):
        hp = _tiny_hp(min_replay_size=4, batch_size=4)
        agent = MaskedDQNAgent(input_dim=2, output_dim=2, hyperparams=hp, level="manager", seed=4)
        for i in range(4):
            agent.store([0.0, 0.0], [True, True], i % 2, 1.0, [1.0, 1.0], [True, True], False)
        loss = agent.train_step()
        assert loss is not None
        assert loss >= 0.0

    def test_target_network_updates_after_interval(self):
        hp = _tiny_hp(min_replay_size=4, batch_size=4, target_update_interval=2)
        agent = MaskedDQNAgent(input_dim=2, output_dim=2, hyperparams=hp, level="manager", seed=5)
        for i in range(4):
            agent.store([0.0, 0.0], [True, True], i % 2, 1.0, [1.0, 1.0], [True, True], False)
        agent.train_step()
        agent.train_step()  # 2. train_step -> target_update_interval'e ulaşır
        target_params = list(agent.target.parameters())
        online_params_after = list(agent.online.parameters())
        for t, o in zip(target_params, online_params_after):
            assert torch.allclose(t, o)

    def test_save_and_load_checkpoint_round_trip(self, tmp_path):
        hp = _tiny_hp()
        agent = MaskedDQNAgent(input_dim=5, output_dim=3, hyperparams=hp, level="worker", seed=6)
        path = tmp_path / "worker_test.pt"
        arch = agent.save_checkpoint(path)
        assert arch == {"input_dim": 5, "output_dim": 3, "hidden_dim": hp.hidden_dim}

        loaded = MaskedDQNAgent.load_checkpoint(path, hyperparams=hp)
        assert loaded.input_dim == 5
        assert loaded.output_dim == 3
        assert loaded.level == "worker"

        x = torch.rand((1, 5))
        with torch.no_grad():
            original_out = agent.online(x)
            loaded_out = loaded.online(x)
        assert torch.allclose(original_out, loaded_out)

    def test_load_checkpoint_uses_saved_hidden_dim_not_callers(self, tmp_path):
        """Regresyon testi: checkpoint hidden_dim=16 ile kaydedilip
        hidden_dim=128 isteyen bir hyperparams ile yüklenirse, mimari
        checkpoint'ten (16) gelmeli — çağıranın 128'i YOK SAYILMALI. Bu
        bug, Faz 4'te evaluate.py'nin gerçek bir smoke-test çalıştırmasında
        (farklı hidden_dim'li checkpoint) yakalandı."""
        small_hp = _tiny_hp(hidden_dim=16)
        agent = MaskedDQNAgent(input_dim=4, output_dim=3, hyperparams=small_hp, level="manager", seed=9)
        path = tmp_path / "small.pt"
        agent.save_checkpoint(path)

        large_hp = _tiny_hp(hidden_dim=128)
        loaded = MaskedDQNAgent.load_checkpoint(path, hyperparams=large_hp)
        assert loaded.online.hidden_dim == 16
        assert loaded.hp.hidden_dim == 16

        x = torch.rand((1, 4))
        with torch.no_grad():
            assert torch.allclose(agent.online(x), loaded.online(x))
