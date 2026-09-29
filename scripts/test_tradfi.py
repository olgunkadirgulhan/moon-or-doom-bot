"""Altın/gümüş/endeks + BIST100 taraması ve tablo testi → data/test_fixed.png, test_bist_long.png, test_bist_short.png"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import ROOT, chart, scanner  # noqa: E402


async def main() -> None:
    t0 = time.time()
    fixed, longs, shorts, failed = await scanner.scan_tradfi()
    print(f"{time.time() - t0:.1f}s  sabit {len(fixed)}  long {len(longs)}  short {len(shorts)}  hata {failed}")
    for r in fixed:
        print(f"  {r['name']:<14} {r['side']:5} {r['signal']:5} skor {r['score']:5.1f} "
              f"fiyat {chart.fmt_price(r['price'])} rr {r['rr']:.2f}")
    print("  LONG :", [(r["symbol"], r["score"]) for r in longs[:5]])
    print("  SHORT:", [(r["symbol"], r["score"]) for r in shorts[:5]])
    for name, rows in (("fixed", fixed), ("bist_long", longs), ("bist_short", shorts)):
        (ROOT / "data" / f"test_{name}.png").write_bytes(chart.summary_table(rows, name, 1000, 10, "Varlık"))


if __name__ == "__main__":
    asyncio.run(main())
