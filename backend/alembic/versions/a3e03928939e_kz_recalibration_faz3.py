"""kz recalibration faz3

TASARIM.md SS12.2.3.1'deki Kz=50000mm (50m) yer tutucusu, fiziksel olcek
acisindan gerceci degildi: Faz 3'un sentetik ureticisi (gercekci slab/urun
boyutlariyla) tek bir order'in teorik haddeleme uzunlugunun (l_i, Table 2)
ortalama ~570,000mm (570m) civarinda oldugunu gosterdi -- yani Kz=50m,
kursun DAHA ILK order'inda bile asilirdi ve H_N (ters genislik kapasitesi)
pratikte hicbir zaman anlamli olamazdi.

Yeni deger: Kz = 3,000,000mm (3km) ~= 5 x ortalama tek-order haddeleme
uzunlugu -- "ilk birkac order'lik bir ramp-up fazi" agirligini korurken,
tek bir order'in hemen zonu kapatmasini engeller. Bu HALA bir muhendislik
tahminidir (gercek fabrika verisi yok) -- bkz. TASARIM.md SS12.4.3.

Revision ID: a3e03928939e
Revises: 41dbbfae3279
Create Date: 2026-08-05 21:55:09.867329

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3e03928939e'
down_revision: Union[str, None] = '41dbbfae3279'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_KZ = 50000
NEW_KZ = 3000000
NEW_DESCRIPTION = (
    "Ters genislik (reverse width) bolgesi esigi: kumulatif haddeleme uzunlugu (mm) - Kz, es. 23. "
    "YER TUTUCU (Faz 3'te sentetik uretici ortalama tek-order haddeleme uzunluguna (~570000mm) "
    "gore ~5x olarak yeniden kalibre edildi, bkz. TASARIM.md SS12.4.3)."
)
OLD_DESCRIPTION = "Ters genislik (reverse width) bolgesi esigi: kumulatif haddeleme uzunlugu (mm) - Kz, es. 23. YER TUTUCU."

constraint_config_table = sa.table(
    "constraint_config",
    sa.column("key", sa.String),
    sa.column("value", sa.Numeric),
    sa.column("description", sa.Text),
)


def upgrade() -> None:
    op.execute(
        constraint_config_table.update()
        .where(constraint_config_table.c.key == "Kz")
        .values(value=NEW_KZ, description=NEW_DESCRIPTION)
    )


def downgrade() -> None:
    op.execute(
        constraint_config_table.update()
        .where(constraint_config_table.c.key == "Kz")
        .values(value=OLD_KZ, description=OLD_DESCRIPTION)
    )
