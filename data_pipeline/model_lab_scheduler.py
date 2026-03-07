import time
from datetime import timedelta

from data_pipeline.common import utc_now
from data_pipeline.model_lab_runner import run_once


def next_hour_plus_delay(delay_seconds: int = 25):
    now = utc_now()
    nxt = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1, seconds=delay_seconds))
    return nxt


def main():
    print("model lab scheduler started (hourly).")
    while True:
        wake = next_hour_plus_delay(25)
        time.sleep(max(0.0, (wake - utc_now()).total_seconds()))
        try:
            run_once()
        except Exception as e:
            print(f"model lab scheduler error: {e}")


if __name__ == "__main__":
    main()
