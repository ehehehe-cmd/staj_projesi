"""Ortak 4 katmanlı MLP tanımı (makale §3.1.2) — Manager ve Worker DQN'leri
bu MİMARİYİ paylaşır, yalnızca giriş/çıkış boyutları farklıdır.

Makale (§3.1.2, s.14): "Each network consists of an input layer that encodes
state features, followed by two fully connected hidden layers with ReLU
activation to perform nonlinear representation learning, and an output layer
that generates action-value predictions." — bu, 4 ağırlıklı katman anlamına
gelir: giriş-projeksiyonu (Linear+ReLU) + 2 gizli katman (Linear+ReLU) +
çıkış katmanı (Linear, aktivasyonsuz — ham Q-değerleri).

``hidden_dim`` sayısal değeri makalede verilmiyor (TASARIM.md §12.2.2:
makale RL hiperparametrelerini paylaşmıyor) — ``training/configs/
default.yaml``'dan gelen bir hiperparametredir, burada sabitlenmez.
"""

from __future__ import annotations

import torch
from torch import nn


class QNetwork(nn.Module):
    """input_dim → hidden_dim (ReLU) → hidden_dim (ReLU) → output_dim (linear).

    ``model_versions.hyperparams`` (TASARIM.md §3.9) bu üç boyutu
    (input_dim/output_dim/hidden_dim) saklar — ``dqn_agent.py``'nin
    checkpoint yükleyicisi ağı buradan yeniden kurar.
    """

    def __init__(self, input_dim: int, output_dim: int, hidden_dim: int = 128) -> None:
        super().__init__()
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.hidden_dim = hidden_dim
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),  # "input layer that encodes state features"
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),  # gizli katman 1
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),  # gizli katman 2
            nn.ReLU(),
            nn.Linear(hidden_dim, output_dim),  # çıkış (Q-değerleri, aktivasyonsuz)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)
