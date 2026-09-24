"""Run the real gold-layer SQL against a tiny in-memory table.

test_api.py mocks query() out, so it can't catch a model that ranks
things backwards. This does.
"""
from pathlib import Path

import duckdb

MODELS = Path(__file__).parent.parent / "models"


def render(model: str, **refs: str) -> str:
    sql = (MODELS / model).read_text()
    sql = sql.replace("{{ config(materialized='table') }}", "")
    for name, table in refs.items():
        sql = sql.replace(f"{{{{ ref('{name}') }}}}", table)
    return sql


def test_best_windows_scores_cheap_clean_slots_highest():
    con = duckdb.connect()
    con.sql("""
        create table pc as select * from (values
            (current_timestamp - interval '10 minutes', 20.0, 200.0, 'current', 40.0),
            (current_timestamp + interval '1 hour',      5.0,  50.0, 'best',    80.0),
            (current_timestamp + interval '2 hours',    15.0, 150.0, 'mid',     50.0),
            (current_timestamp + interval '3 hours',    30.0, 300.0, 'worst',   10.0),
            (current_timestamp - interval '2 hours',     1.0,  10.0, 'past',    90.0)
        ) t(period_utc, value_inc_vat, carbon_intensity, intensity_index, renewable_pct)
    """)
    sql = render("gold/mart_best_windows.sql", mart_price_carbon="pc")
    rows = con.sql(f"select intensity_index, rank, window_score from ({sql})").fetchall()
    by_slot = {slot: (rank, score) for slot, rank, score in rows}

    assert by_slot["best"] == (1, 100)
    assert by_slot["worst"][1] == 0
    assert by_slot["worst"][0] == max(r for r, _ in by_slot.values())
    # the half-hour we're in right now started before now, but /api/now
    # joins on it, so it has to be in the mart
    assert "current" in by_slot
    assert "past" not in by_slot


def test_python_percent_rank_matches_sql():
    """The Schedule tab scores in Python, the headline score in SQL.
    They have to rank the same way or the two disagree about the same slot."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "dashboard"))
    from app import percent_rank

    values = [12.5, 30.0, 12.5, 8.1, 45.2, 30.0, 19.9]
    con = duckdb.connect()
    sql_ranks = [r[0] for r in con.sql(f"""
        select percent_rank() over (order by v) as pr, i
        from (select unnest({values}) as v, generate_subscripts({values}, 1) as i)
        order by i
    """).fetchall()]
    assert percent_rank(values) == sql_ranks
