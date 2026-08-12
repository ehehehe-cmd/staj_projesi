"""Deneyim tekrar tamponu (experience replay buffer) — makale §3.2:

"the exploration trajectories and associated rewards from both the manager
and the worker are independently recorded into their respective experience
replay buffers. Model training commences only after both buffers have
accumulated a minimum of 1,000 experience samples" — bu minimum, çağıranın
(``dqn_agent.py``) sorumluluğundadır (``min_size`` parametresiyle burada
``is_ready()`` üzerinden kontrol edilir); ``ReplayBuffer`` kendisi sade bir
sabit-kapasiteli, rastgele-örneklemeli tampon uygular.
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Transition:
    vector: list[float]
    mask: list[bool]
    action: int
    reward: float
    next_vector: list[float]
    next_mask: list[bool]
    done: bool


class ReplayBuffer:
    def __init__(self, capacity: int, *, seed: int | None = None) -> None:
        self._capacity = capacity
        self._data: deque[Transition] = deque(maxlen=capacity)
        self._rng = random.Random(seed)

    def push(self, transition: Transition) -> None:
        self._data.append(transition)

    def sample(self, batch_size: int) -> list[Transition]:
        if batch_size > len(self._data):
            raise ValueError(f"batch_size ({batch_size}) > buffer içeriği ({len(self._data)})")
        return self._rng.sample(self._data, batch_size)

    def is_ready(self, min_size: int) -> bool:
        return len(self._data) >= min_size

    def __len__(self) -> int:
        return len(self._data)
