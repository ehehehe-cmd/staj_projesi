"""``is_active=true`` checkpoint yükleme + maskelenmiş greedy çıkarım —
TASARIM.md §7: "``model_versions`` tablosundan ``is_active=true`` olan
manager+worker checkpoint'lerini ... doğru mimaride yeniden kurar,
``state_dict`` yükler, salt greedy (argmax, maskelenmiş) çıkarım yapar —
canlıda keşif (exploration) yoktur."

Tasarım kararı (bkz. TASARIM.md §12.6 "tasarımdan sapmalar"): checkpoint'ten
ağ mimarisini yeniden kurma + maskelenmiş-argmax mantığını burada SIFIRDAN
YENİDEN YAZMAK yerine ``app.training.agents.dqn_agent.MaskedDQNAgent``
doğrudan reuse edilir. Gerekçe — İlke 1 (tek kaynak): bu mantık Faz 4'te
zaten bir kez YANLIŞ yazılıp (hidden_dim override bug'ı, bkz. dqn_agent.py
``load_checkpoint`` docstring'i) gerçek bir smoke-test'te yakalanıp
düzeltilmişti; aynı riski burada ikinci kez almak "tek kaynak" ilkesini
ihlal eder. `training/` klasör yapısı yorumundaki "API sürecine hiç import
edilmez" kısıtı, DB'siz epizodik eğitim döngüsünü (env.py/train.py — replay
buffer, optimizer, epsilon takvimi) canlı sürece SIZDIRMAMAK içindir; yan
etkisiz bir checkpoint-yükleyici/ağ sınıfını (``MaskedDQNAgent``) çıkarım
amacıyla reuse etmek bu kısıtın ihlali değildir — ``training/evaluate.py``
(Faz 4) zaten AYNI reuse örüntüsünü (greedy ``select_action`` +
``load_checkpoint``) kendi amacı için uyguluyor.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db import crud
from app.training.agents.dqn_agent import DQNHyperparams, MaskedDQNAgent


class NoActiveModelError(RuntimeError):
    """``is_active=true`` olan bir ``model_versions`` satırı (veya onun
    ``reward_weights`` hiperparametresi) bulunamadığında fırlatılır."""


@dataclass(frozen=True, slots=True)
class ActiveModels:
    """Canlı motorun bir çalışma-zamanı boyunca kullandığı, DB'den bir kez
    yüklenip belleğe alınan çıkarım paketi."""

    manager_agent: MaskedDQNAgent
    worker_agent: MaskedDQNAgent
    manager_model_version_id: int
    worker_model_version_id: int
    k_max: int
    p_max: int
    reward_weights: dict[str, float]


def _load_active_agent(session: Session, *, level: str, device: str) -> tuple[MaskedDQNAgent, int]:
    row = crud.get_active_model_version(session, level=level)
    if row is None:
        raise NoActiveModelError(f"is_active=true olan '{level}' seviyesinde model_versions satırı yok")
    if not row.checkpoint_path:
        raise NoActiveModelError(f"model_versions.id={row.id} ({level}) checkpoint_path boş")
    # Mimari (input/output/hidden_dim) HER ZAMAN checkpoint dosyasının
    # kendisinden gelir (bkz. dqn_agent.load_checkpoint) — burada geçirilen
    # hyperparams sadece lr/gamma/replay gibi çalışma-zamanı iskeleti içindir
    # ve canlı çıkarımda hiçbiri KULLANILMAZ (train_step asla çağrılmaz,
    # yalnızca greedy select_action).
    agent = MaskedDQNAgent.load_checkpoint(row.checkpoint_path, hyperparams=DQNHyperparams(), device=device)
    return agent, row.id


def load_active_models(session: Session, *, device: str = "cpu") -> ActiveModels:
    """``model_versions``'ta ``is_active=true`` olan manager+worker
    checkpoint'lerini yükler. ``k_max``/``p_max`` ayrı bir DB alanından
    OKUNMAZ — manager ağının çıkış boyutu tanım gereği k_max
    (``manager_dqn.build_manager_agent``: ``output_dim=k_max``), worker
    ağınınki p_max'tır; bu yüzden bu iki sayı doğrudan yüklenmiş ağların
    ``output_dim``'inden türetilir — checkpoint kendi kendine yeterlidir,
    ayrı bir DB alanıyla senkron tutulması gereken bir "ikinci kaynak"
    yaratılmaz (İlke 1)."""
    manager_agent, manager_version_id = _load_active_agent(session, level="manager", device=device)
    worker_agent, worker_version_id = _load_active_agent(session, level="worker", device=device)

    manager_row = crud.get_active_model_version(session, level="manager")
    reward_weights = dict((manager_row.hyperparams or {}).get("reward_weights") or {})
    required = {"omega1", "omega2", "r_s", "beta0", "beta1", "beta2"}
    if not required.issubset(reward_weights):
        raise NoActiveModelError(
            f"aktif manager model_versions.hyperparams['reward_weights'] eksik/yetersiz: {reward_weights}"
        )

    return ActiveModels(
        manager_agent=manager_agent,
        worker_agent=worker_agent,
        manager_model_version_id=manager_version_id,
        worker_model_version_id=worker_version_id,
        k_max=manager_agent.output_dim,
        p_max=worker_agent.output_dim,
        reward_weights=reward_weights,
    )
