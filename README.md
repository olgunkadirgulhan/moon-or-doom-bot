# Moon or Doom — Kişisel Telegram Sinyal Botu

1h/4h/8h/1d destek-direnç + trend/RSI/on-chain skorlaması ile AL/SAT/BEKLE sinyali üretir,
özet tablo ve 2×2 grafik PNG'lerini sadece senin Telegram sohbetine gönderir.
⚠️ Yatırım tavsiyesi değildir; bot emir göndermez.

## Kurulum (Windows)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env   # sonra .env'i doldur
```

1. **TELEGRAM_BOT_TOKEN**: Telegram'da @BotFather → `/newbot` → verilen token.
2. **ALLOWED_CHAT_ID**: boş bırakıp botu başlat, bota `/start` yaz; konsolda
   `Gelen chat_id=...` satırı çıkar. O sayıyı `.env`'e yaz ve botu yeniden başlat.
3. **ETHERSCAN_API_KEY** (opsiyonel): etherscan.io → API Keys. Boşsa on-chain skoru 0 olur.
   Not: Etherscan V2 free planı bazı zincirleri (ör. BSC/Base) kapsamayabilir; o coinlerde
   grafikte hata nedeni yazar.

Çalıştır: `.venv\Scripts\python -m bot.main` (veya çöktüğünde yeniden başlatan `run.bat`).

## Komutlar

| Komut | İş |
|---|---|
| `/scan` | Tüm liste → özet tablo + AL/SAT coin grafikleri |
| `/coin ETH` | Tek coin grafik + bileşen detayı + balina transferleri |
| `/list` | İzleme listesi |
| `/watch add PEPE` · `/watch rm PEPE` | Listeyi düzenle |
| `/settings` · `/settings min_rr 2` | Ayarları gör / değiştir (ör. `/settings candidate_markets crypto,bist`, `/settings candidate_sides long,short`) |

Ayar anahtarları: `buy_threshold`, `sell_threshold`, `min_rr`, `rr_penalty`,
`report_hours` (ör. `0,6,12,18`, en az 4), `top_n` (≥10), `universe_size`,
`alerts` (on/off), `weights.trend|proximity|rsi|confluence|onchain`.

Otomatik rapor: her gün 00:00, 06:00, 12:00, 18:00 (İstanbul) — tablo + listedeki tüm coinlerin grafikleri.

**Trend Kırılımı** (ayrı strateji, `bot/trend_job.py`, her gün 03:10 İstanbul): günlük kapanış 20 günlük zirveyi
hacimle (1.3×) kırar, fiyat EMA200 üstünde, BTC düşüş trendinde değil, öncesinde volatilite sıkışmış (120 günün alt yarısı) → AL. Stop 2 ATR, sonra her gün
"en yüksek kapanış − 3 ATR" avize stop; sabit hedef yok, en fazla 30 gün. %0.5 risk, max 6 açık.
Backtest (eğitim + dokunulmamış test, dayanıklılık): `tracking/research_trend.md`. Canlı: `tracking/trend_results.csv`.

## Yapılandırma

- `config/coins.yaml` — her zaman izlenecek coinler (`manual`) ve on-chain için token kontratları.
- `config/exchange_wallets.yaml` — borsa cüzdanları. Adresleri `brianleect/etherscan-labels`'tan
  doğrulayarak genişlet; her ek adres token başına 1 API çağrısı demek.

## Testler

```powershell
.venv\Scripts\python scripts\test_levels.py BTC   # 4 TF seviyeleri
.venv\Scripts\python scripts\test_chart.py BTC    # data/test_btc.png + tarama + data/test_table.png
```

## 7/24

- Linux: `deploy/moon-or-doom.service` (systemd) veya
  `docker build -t moon-or-doom . && docker run -d --restart=always --env-file .env -v %cd%/data:/app/data moon-or-doom`
