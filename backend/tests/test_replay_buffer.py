"""training/agents/replay_buffer.py birim testleri — Faz 4."""

import pytest

from app.training.agents.replay_buffer import ReplayBuffer, Transition


def _dummy_transition(action: int = 0) -> Transition:
    return Transition(
        vector=[1.0, 2.0],
        mask=[True, False],
        action=action,
        reward=1.0,
        next_vector=[3.0, 4.0],
        next_mask=[True, True],
        done=False,
    )


class TestReplayBuffer:
    def test_push_and_len(self):
        buf = ReplayBuffer(capacity=10)
        assert len(buf) == 0
        buf.push(_dummy_transition())
        assert len(buf) == 1

    def test_is_ready_respects_min_size(self):
        buf = ReplayBuffer(capacity=10)
        for _ in range(3):
            buf.push(_dummy_transition())
        assert buf.is_ready(3) is True
        assert buf.is_ready(4) is False

    def test_capacity_evicts_oldest(self):
        buf = ReplayBuffer(capacity=3)
        for i in range(5):
            buf.push(_dummy_transition(action=i))
        assert len(buf) == 3
        actions = {t.action for t in buf.sample(3)}
        assert actions == {2, 3, 4}

    def test_sample_raises_when_not_enough_data(self):
        buf = ReplayBuffer(capacity=10)
        buf.push(_dummy_transition())
        with pytest.raises(ValueError):
            buf.sample(5)

    def test_sample_is_reproducible_with_seed(self):
        buf1 = ReplayBuffer(capacity=10, seed=42)
        buf2 = ReplayBuffer(capacity=10, seed=42)
        for i in range(10):
            buf1.push(_dummy_transition(action=i))
            buf2.push(_dummy_transition(action=i))
        sample1 = [t.action for t in buf1.sample(5)]
        sample2 = [t.action for t in buf2.sample(5)]
        assert sample1 == sample2
