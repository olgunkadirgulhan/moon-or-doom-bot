"""Faz 1 testi: BTC için 4 TF destek/direnç seviyelerini yazdırır."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import data, levels  # noqa: E402
from core.indicators import add_indicators, last_atr  # noqa: E402


async def main(symbol: str = "BTC") -> None:
    try:
        frames = {tf: add_indicators(df) for tf, df in (await data.fetch_all_tf(symbol)).items()}
    finally:
        await data.close()
    price = float(frames["1h"]["Close"].iloc[-1])
    lv = {tf: levels.compute_levels(df, tf, price) for tf, df in frames.items()}
    levels.annotate_confluence(lv, 0.5 * last_atr(frames["4h"]))

    print(f"{symbol} fiyat: {price:,.2f}")
    for tf, l in lv.items():
        fmt = lambda xs: ", ".join(f"{p:,.2f}(g{s:.0f}{'*' * (c > 1)})" for p, s, c in xs)
        print(f"[{tf}] ATR={l['atr']:,.2f}")
        print(f"   direnç: {fmt(l['resistances'])}")
        print(f"   destek: {fmt(l['supports'])}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "BTC"))
