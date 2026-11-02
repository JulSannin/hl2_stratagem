"""Regression snapshot for stratagem input codes cross-checked on 2026-10-30."""
import csv
from collections import defaultdict
from pathlib import Path


EXPECTED_CODES = {
    "Оружие поддержки": """DLULLD DLDUUR DLRUD DRDULL DLULUU DRUURU DLRRU DLRRD DLRLU DDLUR DDLUD DDLUL DDUDD DLUDU DLULD DLULUU DRULR DLRRL DLDUL DDULR DLDUUL DLRDUU DLDUR DLUDD DLDRUL DLUDR DURDD DLULR DUULR DRDULR DRDLUR DDUDR DLUDL""".split(),
    "Орбитальные и авиаудары": """URUL URDDD URDR URDDR URLR URDU URUD URRR RRDLRD RDUULDD RRR RRLD RRDR RDLUU RDURD RRDLRU RRU RUDDR RRDU RDRDRD""".split(),
    "Оборонительные установки": """DURULU DURULR DURDUU DURL DURDL DURDUR DURRD DURDR DURRU DURRL DULRRR DRDLR DULRRL DDLRLR DLUR DLLR DLUU DLLD""".split(),
    "Рюкзаки": """DULURD DULURL DULULL DULURR DULURU DLDUUD DRUUU DLRDLR UUDU UUDLR DLDDUL DULRLR DULRUU""".split(),
    "Техника": """LDRULDD LDRULDU LDRURLU LDRLRDU LDRDRDU LDLLDUR LDRLDUU UDRDLDULR LDRDLDUDU""".split(),
    "Стратагемы заданий": """UUDDLRLR UUDDRD ULRDUU UULUR LUDRDD DULDURDU RRLL DDLRDD LRUUU RUUD UULRDD DDDDDUU DUDU UDUDUD LRUUU""".split(),
    "По умолчанию": """UDRLU DDUR UDRU""".split(),
}


def test_all_111_arrow_codes_match_the_2026_10_30_reference_snapshot():
    catalog_path = Path(__file__).resolve().parents[1] / "stratagems.tsv"
    grouped = defaultdict(list)
    with catalog_path.open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.reader(source, delimiter="\t"):
            if row:
                grouped[row[0]].append(row[2].strip().upper())

    assert set(grouped) == set(EXPECTED_CODES)
    assert sum(map(len, grouped.values())) == 111
    for category, expected in EXPECTED_CODES.items():
        assert grouped[category] == expected, category
