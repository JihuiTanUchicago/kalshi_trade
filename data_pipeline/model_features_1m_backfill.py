from datetime import timedelta

from data_pipeline.common import get_db_conn, parse_iso_to_dt
from data_pipeline.model_features_1m_builder import build_row, upsert_row


def main() -> None:
    conn = get_db_conn()
    total = 0
    target_cache = {}
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(snapshot_minute_utc) AS mn, MAX(snapshot_minute_utc) AS mx FROM trade_quote_features_1m")
        rng = cur.fetchone()
        if not rng or not rng.get("mn"):
            print("No trade_quote_features_1m rows found; nothing to backfill.")
            return

        t = rng["mn"]
        end = rng["mx"]
        print(f"Backfilling model_features_1m from {t} to {end}")
        while t <= end:
            row = build_row(cur, parse_iso_to_dt(t.isoformat() + "Z"), target_cache)
            upsert_row(cur, row)
            total += 1
            if total % 250 == 0:
                print(f"backfill progress rows={total} minute={t}")
            t = t + timedelta(minutes=1)

    conn.close()
    print(f"Done model_features_1m backfill rows={total}")


if __name__ == "__main__":
    main()
