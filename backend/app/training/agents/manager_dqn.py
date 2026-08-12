"""Manager DQN ajanı — ``dqn_agent.MaskedDQNAgent``'ın manager boyutlarıyla
kurulmuş hâli (bkz. ``dqn_agent.py`` modül-üstü yorumu: ortak mantık orada).

Giriş boyutu ``state_builder.ManagerState.to_vector(k_max)``'in ürettiği
vektör uzunluğuyla BİREBİR aynı olmalıdır — bunu elle (magic number olarak)
hesaplamak yerine, sıfır bir ``ManagerState`` inşa edip gerçek ``to_vector``
çıktısının uzunluğunu ölçüyoruz; böylece ``state_builder.py`` ileride
genişlerse (örn. yeni bir özellik eklenirse) bu dosyada hiçbir değişiklik
gerekmez.
"""

from __future__ import annotations

from app.domain.state_builder import ManagerState
from app.training.agents.dqn_agent import DQNHyperparams, MaskedDQNAgent


def manager_input_dim(k_max: int) -> int:
    dummy = ManagerState(
        available_groups=(),
        reverse_width_capability=False,
        order_count=0,
        course_index=0,
        last_attributes=None,
    )
    return len(dummy.to_vector(k_max))


def build_manager_agent(
    *,
    k_max: int,
    hyperparams: DQNHyperparams,
    device: str = "cpu",
    seed: int | None = None,
) -> MaskedDQNAgent:
    return MaskedDQNAgent(
        input_dim=manager_input_dim(k_max),
        output_dim=k_max,
        hyperparams=hyperparams,
        level="manager",
        device=device,
        seed=seed,
    )
