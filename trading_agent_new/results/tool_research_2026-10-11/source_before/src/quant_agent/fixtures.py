"""Labeled synthetic engineering data; it can never qualify for paper alpha."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import csv
import json
import math

from .common import GateError, file_hash
from .data import TABLES, Dataset


def make_fixture(directory: str | Path) -> Dataset:
    directory = Path(directory)
    if directory.exists() and any(directory.iterdir()):
        raise GateError("Fixture output must be empty; existing datasets are never overwritten")
    directory.mkdir(parents=True,exist_ok=True)
    days = []
    day = date(2026,6,1)
    while day <= date(2026,10,8):
        if day.weekday()<5: days.append(day.isoformat())
        day += timedelta(days=1)
    ny = ZoneInfo("America/New_York")
    def at(day,hour): return datetime.combine(date.fromisoformat(day),time(hour),ny).isoformat()
    rows = {name:[] for name in TABLES}
    master = [("S-A","AAA","common_stock"),("S-B","BBB","common_stock"),("F-SPY","SPY","etf"),("S-IPO","NEW","common_stock")]
    rows["assets"] = [dict(asset_id=a,symbol=s,kind=k,currency="USD",leverage_factor=1,inverse=0) for a,s,k in master]
    prices = {"S-A":100.0,"S-B":85.0,"F-SPY":200.0,"S-IPO":70.0}
    for i,day in enumerate(days):
        settled = date.fromisoformat(day)+timedelta(days=1)
        while settled.weekday()>4: settled += timedelta(days=1)
        rows["sessions"].append(dict(session=day,open_at=datetime.combine(date.fromisoformat(day),time(9,30),ny).isoformat(),
                                     close_at=at(day,16),settlement_date=settled.isoformat()))
        rows["financing"].append(dict(session=day,credit_rate=0.015,debit_rate=0.065,reference_rate=0.03,available_at=at(day,8)))
        for j,(asset,symbol,kind) in enumerate(master):
            eligible = not (asset=="S-IPO" and i<35) and not (asset=="S-B" and i>=80)
            rows["membership"].append(dict(session=day,asset_id=asset,eligible=int(eligible),available_at=at(day,8)))
            if kind=="common_stock":
                rows["borrow"].append(dict(session=day,asset_id=asset,shares=0 if not eligible or (asset=="S-B" and i==60) else 100_000,
                                            fee_rate=0.025,available_at=at(day,8)))
            if not eligible: continue
            old = prices[asset]
            if asset=="S-A" and i==65:
                old /= 2
                rows["actions"].append(dict(session=day,asset_id=asset,kind="split",value=2,pay_date="",available_at=at(days[i-2],8)))
            if asset=="S-A" and i==50:
                old -= 1
                rows["actions"].append(dict(session=day,asset_id=asset,kind="dividend",value=1,pay_date=days[i+5],available_at=at(days[i-5],8)))
            change = (0.001 if j%2==0 else -0.0004)+0.007*math.sin(i*0.37+j)
            opening = old*(1+0.001*math.cos(i+j))
            closing = old*(1+change)
            rows["bars"].append(dict(session=day,asset_id=asset,open=opening,high=max(opening,closing)*1.001,
                                      low=min(opening,closing)*0.999,close=closing,volume=1_000_000,available_at=at(day,16)))
            prices[asset] = closing
        if i==80:
            rows["actions"].append(dict(session=day,asset_id="S-B",kind="delist_cash",value=prices["S-B"]*0.8,pay_date="",available_at=at(days[i-1],8)))
    files = {}
    for name,columns in TABLES.items():
        path = directory/f"{name}.csv"
        with path.open("w",newline="") as stream:
            writer = csv.DictWriter(stream,fieldnames=sorted(columns))
            writer.writeheader();writer.writerows(rows[name])
        files[name] = {"path":path.name,"sha256":file_hash(path)}
    next_day = date.fromisoformat(days[-1])+timedelta(days=1)
    manifest = {"schema_version":1,"quality":"synthetic","source":"deterministic engineering fixture; weekdays are NOT an exchange calendar",
                "files":files,"next_session":{"session":next_day.isoformat(),"previous_session":days[-1],
                                                "open_at":datetime.combine(next_day,time(9,30),ny).isoformat()}}
    (directory/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    return Dataset(directory)
