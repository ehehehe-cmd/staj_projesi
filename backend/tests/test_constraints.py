"""core/constraints.py birim testleri — Faz 2'nin pragmatik eklentisi.

Bkz. TASARIM.md §12.3.3: domain katmanının Δw/Δt/Δh/Δθ/Kz/Lr/m_min/m_max/
soft_transition_limit degerlerine ihtiyaci oldugu icin bu kucuk dataclass
Faz 2 kapsamina dahil edildi.
"""

import pytest

from app.core.constraints import RollingConstraints


def test_from_mapping_builds_expected_dataclass():
    values = {
        "delta_w": "50",
        "delta_t": "0.5",
        "delta_h": "5",
        "delta_theta": "30",
        "Kz": "50000",
        "Lr": "3",
        "m_min": "60",
        "m_max": "100",
        "soft_transition_limit": "3",
    }
    constraints = RollingConstraints.from_mapping(values)
    assert constraints == RollingConstraints(
        delta_w=50.0,
        delta_t=0.5,
        delta_h=5.0,
        delta_theta=30.0,
        kz=50000.0,
        lr=3,
        m_min=60,
        m_max=100,
        soft_transition_limit=3,
    )


def test_from_mapping_raises_on_missing_key():
    values = {"delta_w": 50.0}
    with pytest.raises(ValueError, match="eksik anahtar"):
        RollingConstraints.from_mapping(values)


def test_is_frozen_and_hashable():
    constraints = RollingConstraints(
        delta_w=50.0, delta_t=0.5, delta_h=5.0, delta_theta=30.0, kz=50000.0, lr=3, m_min=60, m_max=100, soft_transition_limit=3
    )
    with pytest.raises(AttributeError):
        constraints.delta_w = 100.0  # type: ignore[misc]
    hash(constraints)  # frozen dataclass -> hashlenebilir olmali
