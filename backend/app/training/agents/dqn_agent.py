"""Ortak maskelenmiş-DQN ajan mantığı — Manager ve Worker'ın PAYLAŞTIĞI
tek gerçek fark, giriş/çıkış boyutlarıdır (bkz. ``manager_dqn.py`` /
``worker_dqn.py``).

Tasarım kararı (TASARIM.md'de bu dosya adıyla planlanmamıştı — bkz. Faz 4
kaydı §12.5): ``manager_dqn.py`` ve ``worker_dqn.py`` içine aynı ~150
satırlık DQN mantığını (ε-greedy + maskeleme, replay örnekleme, hedef ağ
güncellemesi, checkpoint I/O) iki kez yazmak yerine, bu mantık burada TEK
YERDE toplanır; iki dosya sadece boyut/isimlendirmeye özgü ince birer
fabrika fonksiyonu sağlar. Bu, Faz 1/2/3'ün "önceden planlanmamış ama
gerekçeli" ek dosya ekleme örüntüsüyle (``core/constraints.py``,
``db/crud.py``) aynı ruhtadır.

Eşleştirme:
- eş. 36 (ε-greedy): ``select_action`` — ``ρ`` burada ``epsilon``.
- §3.2 "minimum 1,000 örnek": ``DQNHyperparams.min_replay_size`` (varsayılan
  1000, ``train_step`` bu eşiğe kadar ``None`` döndürüp eğitimi erteler).
- "Action Mask... invalid aksiyonlar `-inf` alır": hem keşif (rastgele seçim
  SADECE geçerli aksiyonlar arasından) hem açgözlü (`-inf` maskeleme +
  argmax) kolunda uygulanır.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from pathlib import Path

import torch
from torch import nn

from app.training.agents.networks import QNetwork
from app.training.agents.replay_buffer import ReplayBuffer, Transition

_NEG_INF = float("-inf")


@dataclass(frozen=True, slots=True)
class DQNHyperparams:
    """RL hiperparametreleri — TASARIM.md §12.2.2: makale sayısal değer
    vermiyor (ticari gizli veriyle kalibre edilmiş), bu yüzden tüm alanlar
    ``training/configs/default.yaml``'dan gelen mühendislik tahminidir.
    Tek istisna ``min_replay_size=1000`` — makale §3.2'de açıkça belirtilir.
    """

    hidden_dim: int = 128
    learning_rate: float = 1e-3
    gamma: float = 0.99
    batch_size: int = 64
    target_update_interval: int = 200
    replay_capacity: int = 50_000
    min_replay_size: int = 1000
    epsilon_start: float = 1.0
    epsilon_end: float = 0.05
    epsilon_decay_steps: int = 20_000


class MaskedDQNAgent:
    """Tek bir seviyenin (manager YA DA worker) DQN ajanı.

    ``input_dim``/``output_dim`` çağıran tarafından hesaplanır (bkz.
    ``manager_dqn.manager_input_dim`` / ``worker_dqn.worker_input_dim``) —
    bu sınıf domain katmanının state/mask temsiliyle ilgili HİÇBİR şey
    bilmez, salt vektör/maske üzerinde çalışır (TASARIM.md §1 ilke 1:
    state encoding tek kaynağı ``domain/state_builder.py``'dir).
    """

    def __init__(
        self,
        *,
        input_dim: int,
        output_dim: int,
        hyperparams: DQNHyperparams,
        level: str,
        device: str = "cpu",
        seed: int | None = None,
    ) -> None:
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.level = level
        self.hp = hyperparams
        self.device = torch.device(device)

        self.online = QNetwork(input_dim, output_dim, hyperparams.hidden_dim).to(self.device)
        self.target = QNetwork(input_dim, output_dim, hyperparams.hidden_dim).to(self.device)
        self.target.load_state_dict(self.online.state_dict())
        self.target.eval()

        self.optimizer = torch.optim.Adam(self.online.parameters(), lr=hyperparams.learning_rate)
        self.replay = ReplayBuffer(hyperparams.replay_capacity, seed=seed)

        self._rng = random.Random(seed)
        self.global_step = 0
        self.train_steps = 0

        # TASARIM.md §14.1.B tanı sinyalleri — yalnızca en son train_step()
        # çağrısının değerlerini tutar (loss ile aynı "son değer" örüntüsü,
        # bkz. train.py::EpisodeStats). train_step() replay hazır olmadan
        # (min_replay_size) hiç çağrılmadıysa None kalır.
        self.last_grad_norm: float | None = None
        self.last_reward_batch_std: float | None = None

    # -- keşif / karar --

    def epsilon(self) -> float:
        """eş. 36'daki ``ρ`` — global_step'e göre doğrusal azalan keşif eşiği."""
        hp = self.hp
        if hp.epsilon_decay_steps <= 0:
            return hp.epsilon_end
        frac = min(1.0, self.global_step / hp.epsilon_decay_steps)
        return hp.epsilon_start + frac * (hp.epsilon_end - hp.epsilon_start)

    def select_action(self, vector: list[float], mask: list[bool], *, greedy: bool = False) -> int:
        """eş. 36: x≤ρ → rastgele (SADECE maskelenmemiş aksiyonlar arasından);
        aksi halde argmax Q(s,·;θ) (maskelenmiş, geçersizler -inf).

        ``greedy=True`` canlı çıkarım/evaluate.py'nin kullandığı, keşifsiz
        salt-argmax modudur (TASARIM.md §7: "canlıda keşif (exploration)
        yoktur").
        """
        valid = [i for i, ok in enumerate(mask) if ok]
        if not valid:
            raise ValueError(f"{self.level}: boş maske ile select_action çağrıldı")

        if not greedy:
            eps = self.epsilon()
            self.global_step += 1
            if self._rng.random() < eps:
                return self._rng.choice(valid)

        with torch.no_grad():
            q = self.online(torch.tensor([vector], dtype=torch.float32, device=self.device)).squeeze(0)
            masked = q.clone()
            for i in range(self.output_dim):
                if i not in valid:
                    masked[i] = _NEG_INF
            return int(torch.argmax(masked).item())

    # -- deneyim / eğitim --

    def store(
        self,
        vector: list[float],
        mask: list[bool],
        action: int,
        reward: float,
        next_vector: list[float] | None,
        next_mask: list[bool] | None,
        done: bool,
    ) -> None:
        nv = next_vector if next_vector is not None else [0.0] * self.input_dim
        nm = next_mask if next_mask is not None else [False] * self.output_dim
        self.replay.push(Transition(list(vector), list(mask), action, reward, nv, nm, done))

    def train_step(self) -> float | None:
        if not self.replay.is_ready(self.hp.min_replay_size):
            return None
        batch = self.replay.sample(self.hp.batch_size)

        states = torch.tensor([t.vector for t in batch], dtype=torch.float32, device=self.device)
        actions = torch.tensor([t.action for t in batch], dtype=torch.long, device=self.device)
        rewards = torch.tensor([t.reward for t in batch], dtype=torch.float32, device=self.device)
        next_states = torch.tensor([t.next_vector for t in batch], dtype=torch.float32, device=self.device)
        dones = torch.tensor([t.done for t in batch], dtype=torch.float32, device=self.device)
        next_masks = torch.tensor([t.next_mask for t in batch], dtype=torch.bool, device=self.device)

        q_values = self.online(states).gather(1, actions.unsqueeze(1)).squeeze(1)

        with torch.no_grad():
            next_q = self.target(next_states)
            next_q = next_q.masked_fill(~next_masks, _NEG_INF)
            # Bir subtask/episode'un GERÇEKTEN son adımı (done=True) için
            # bootstrap kullanılmaz; next_mask'in tamamen boş olabileceği
            # (çağıranın done=True'da sentetik sıfır maske geçtiği) durumlar
            # da bu yüzden zaten (1-done) çarpanıyla etkisizleşir.
            best_next_q = next_q.max(dim=1).values
            best_next_q = torch.nan_to_num(best_next_q, neginf=0.0)
            target = rewards + self.hp.gamma * best_next_q * (1.0 - dones)

        # Huber/SmoothL1 (MSE yerine) + gradient clipping — TEST.md §9'un
        # önerdiği ama uygulanmadığı iki stabilizasyon tekniği. worker/loss
        # ölçümlerinde uç TD-hataları (gözlemlenen max=213.5 vs. medyan
        # ~15) MSE altında kareleniyordu; Huber, |hata|>1 bölgesinde
        # doğrusala döner, tek bir uç örneğin gradyanı domine etmesini
        # engeller. clip_grad_norm_ buna ek bir güvenlik ağıdır.
        loss = nn.functional.smooth_l1_loss(q_values, target)
        self.optimizer.zero_grad()
        loss.backward()
        grad_norm = nn.utils.clip_grad_norm_(self.online.parameters(), max_norm=10.0)
        self.optimizer.step()

        self.last_grad_norm = float(grad_norm.item())
        # TEST.md §9'un "ilk şüpheli" hipotezi: worker ödülü -2..+20 gibi geniş
        # bir aralıkta — örneklenen batch'in ödül std'si bu değişkenliği
        # doğrudan gözlemlenebilir kılar (bkz. §14.1.B "nasıl" adım 2).
        self.last_reward_batch_std = float(rewards.std().item()) if len(rewards) > 1 else 0.0

        self.train_steps += 1
        if self.train_steps % self.hp.target_update_interval == 0:
            self.target.load_state_dict(self.online.state_dict())

        return float(loss.item())

    # -- checkpoint I/O --

    def save_checkpoint(self, path: str | Path, *, extra: dict | None = None) -> dict:
        """Checkpoint'i diske yazar; ``model_versions.hyperparams``'a
        (TASARIM.md §3.9) yazılacak sözlüğü döndürür — "inference.py
        checkpoint'i yüklerken ağ mimarisini bu alandan yeniden kurar"
        gereksinimini karşılamak için input_dim/output_dim/hidden_dim
        checkpoint dosyasının İÇİNE de gömülür (çift kayıt: hem dosyada
        hem DB'de — DB satırı kaybolsa bile checkpoint kendi kendine
        yeterli kalır).
        """
        arch = {"input_dim": self.input_dim, "output_dim": self.output_dim, "hidden_dim": self.hp.hidden_dim}
        payload = {
            "level": self.level,
            "architecture": arch,
            "state_dict": self.online.state_dict(),
            "extra": extra or {},
        }
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(payload, path)
        return arch

    @classmethod
    def load_checkpoint(
        cls,
        path: str | Path,
        *,
        hyperparams: DQNHyperparams,
        device: str = "cpu",
        seed: int | None = None,
    ) -> "MaskedDQNAgent":
        payload = torch.load(Path(path), map_location=device, weights_only=False)
        arch = payload["architecture"]
        # Mimari (input/output/hidden_dim) her zaman CHECKPOINT'TEN gelir,
        # çağıranın hyperparams'ından DEĞİL — aksi halde ``state_dict``
        # boyutları uyuşmaz (bkz. TASARIM.md §12.5: bu bug gerçek bir
        # evaluate.py smoke-test çalıştırmasında yakalandı). Diğer tüm
        # çalışma-zamanı hiperparametreleri (lr, gamma, replay ayarları,
        # epsilon takvimi) serbestçe çağırandan gelir — bunlar ağırlıkların
        # bir parçası değildir.
        hyperparams = replace(hyperparams, hidden_dim=arch["hidden_dim"])
        agent = cls(
            input_dim=arch["input_dim"],
            output_dim=arch["output_dim"],
            hyperparams=hyperparams,
            level=payload["level"],
            device=device,
            seed=seed,
        )
        agent.online.load_state_dict(payload["state_dict"])
        agent.target.load_state_dict(payload["state_dict"])
        return agent
