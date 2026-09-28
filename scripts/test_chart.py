"""Faz 2/3 testi: BTC 2×2 grafik + sinyal, tam tarama + özet tablo → data/*.png"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from core import ROOT, chart, data, scanner  # noqa: E402


async def main(symbol: str) -> None:
    try:
        res = await scanner.analyze(symbol)
        (ROOT / "data" / f"test_{symbol.lower()}.png").write_bytes(chart.coin_chart(res))
        print({k: res[k] for k in ("symbol", "signal", "score", "entry", "sl", "tp1", "tp2", "rr", "rr_low")})
        print("bileşenler:", res["components"], "| on-chain:", res["onchain"].get("reason") or res["onchain"]["score"])

        t0 = time.time()
        longs, shorts, failed = await scanner.scan()
        (ROOT / "data" / "test_table_long.png").write_bytes(chart.summary_table(longs, "LONG"))
        (ROOT / "data" / "test_table_short.png").write_bytes(chart.summary_table(shorts, "SHORT"))
        print(f"tarama {time.time() - t0:.1f}s, {len(longs)} long + {len(shorts)} short, hata: {failed}")
        for r in longs + shorts:
            print(f"  {r['symbol']:6} {r['side']:5} {r['signal']:5} {r['score']:5.1f}  rr={r['rr']:.2f}{' ⚠' if r['rr_low'] else ''}")
    finally:
        await data.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "BTC"))
