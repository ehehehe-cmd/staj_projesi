"""Worker DQN ajanı — ``dqn_agent.MaskedDQNAgent``'ın worker boyutlarıyla
kurulmuş hâli. Bkz. ``manager_dqn.py``'nin modül-üstü yorumu; aynı
"gerçek to_vector çıktısını ölç" yaklaşımı burada da uygulanır.
"""

from __future__ import annotations

from app.domain.dto import OrderAttributes
from app.domain.state_builder import WorkerState
from app.training.agents.dqn_agent import DQNHyperparams, MaskedDQNAgent

_ZERO_ATTRS = OrderAttributes(width_mm=0.0, thickness_mm=0.0, hardness=0.0, heating_temp_c=0.0)


def worker_input_dim(*, k_max: int, p_max: int) -> int:
    dummy = WorkerState(
        available_transitions=(),
        available_groups=(),
        used_transition_count=0,
        reverse_width_event_count=0,
        reverse_width_capability=False,
        last_attributes=None,
        target_attributes=_ZERO_ATTRS,
    )
    return len(dummy.to_vector(k_max=k_max, p_max=p_max))


def build_worker_agent(
    *,
    k_max: int,
    p_max: int,
    hyperparams: DQNHyperparams,
    device: str = "cpu",
    seed: int | None = None,
) -> MaskedDQNAgent:
    return MaskedDQNAgent(
        input_dim=worker_input_dim(k_max=k_max, p_max=p_max),
        output_dim=p_max,
        hyperparams=hyperparams,
        level="worker",
        device=device,
        seed=seed,
    )
