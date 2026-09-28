# PROGRESS

- Faz 0: token-saver skill, venv, requirements. (Mevcut 4H S/R reposu yoktu → levels.py spec Bölüm 4'e göre sıfırdan yazıldı.)
- Faz 1: core/data.py (ccxt+SQLite cache), indicators.py, levels.py (fraktal+ATR kümeleme+konfluens). Test: scripts/test_levels.py
- Faz 2: core/chart.py — 2×2 grafik (1600×1200, koyu) + özet tablo PNG. Test: scripts/test_chart.py → data/test_btc.png, data/test_table.png
- Faz 3: core/signal.py (5 bileşen, R:R cezası), core/scanner.py (evren + sıralama), core/settings.py
- Faz 4: bot/ main, handlers, auth, report, jobs (00/06/12/18 İstanbul + opsiyonel SL/TP uyarı). Duman testi geçti; gerçek token ile test edilmedi.
- Faz 5: core/onchain.py (Etherscan V2, cüzdan başına tokentx, 7g günlük netflow, balina) + config yaml'ları. API key ile test edilmedi.
- Faz 6: hata yönetimi, rate limit, Dockerfile, deploy/moon-or-doom.service, run.bat.
- GitHub Actions: .github/workflows/report.yml + bot/oneshot.py, gunde 4 rapor (00/06/12/18 Istanbul). Binance verisi data-api.binance.vision uzerinden (ABD engeli yok). Komutlar sadece yerel bot.main acikken calisir.
