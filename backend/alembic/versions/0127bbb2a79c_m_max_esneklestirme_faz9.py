"""m_max esneklestirme faz9

TASARIM.md SS14.3.J: kurs kapasitesi icin SERT tavan (m_max) 100'den 120'ye
yukseltildi. m_max hala action_mask'in kullandigi gercek/sert bir sinirdir
(bunu asan bir yerlestirme YAPILAMAZ) -- ama artik 100 ile 120 arasi bir
"yasak bolge" degil, sadece 100'un (yeni, ayrica reward_weights.m_target
olarak eklenen yumusak hedef) uzerine cikmak yumusak bir odul cezasi
(omega3) tasir. Boylece bir grubun kapasiteyi 100'de degil TAM kendi
buyuklugunde bitirmesine (ornegin 103) izin verilir -- 3 slab'lik bir artik
icin ayri, verimsiz bir kurs acilmasi onlenir. Gerekce/olcum: docs/SONUCLAR.md
SS12, docs/TASARIM.md SS14.3.J.

Revision ID: 0127bbb2a79c
Revises: a3e03928939e
Create Date: 2026-08-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0127bbb2a79c'
down_revision: Union[str, None] = 'a3e03928939e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_M_MAX = 100
NEW_M_MAX = 120
NEW_DESCRIPTION = (
    "Bir haddeleme kursundaki maksimum izin verilen order sayisi - m_max, es. 11. YER TUTUCU "
    "(TASARIM.md SS14.3.J geregi 100'den 120'ye yukseltildi: artik SERT tavan burasi, 100 ise "
    "reward_weights.m_target'ta tutulan YUMUSAK bir hedef -- 100-120 arasi yasak degil, sadece "
    "omega3 ile hafifce cezali)."
)
OLD_DESCRIPTION = "Bir haddeleme kursundaki maksimum izin verilen order sayisi - m_max, es. 11. YER TUTUCU (makale SS2.2.2: 'kurs tipik olarak 60-100 order icerir')."

constraint_config_table = sa.table(
    "constraint_config",
    sa.column("key", sa.String),
    sa.column("value", sa.Numeric),
    sa.column("description", sa.Text),
)


def upgrade() -> None:
    op.execute(
        constraint_config_table.update()
        .where(constraint_config_table.c.key == "m_max")
        .values(value=NEW_M_MAX, description=NEW_DESCRIPTION)
    )


def downgrade() -> None:
    op.execute(
        constraint_config_table.update()
        .where(constraint_config_table.c.key == "m_max")
        .values(value=OLD_M_MAX, description=OLD_DESCRIPTION)
    )
