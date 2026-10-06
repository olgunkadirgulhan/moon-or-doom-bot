# Trend aileleri araştırması

- 26 coin · eğitim/test ayrımı 2025-12-13T00:30:00 · komisyon %0.1 + kayma %0.05 · hesap: %1.0 risk, max 3 açık

| Aile | Eğitim (tüm sinyaller) | Test (tüm sinyaller) | Test (hesap kurallarıyla) |
|---|---|---|---|
| pullback | 406 · kazanma %40 · -0.06R · PF 0.88 · t=-1.1 | 50 · kazanma %74 · +0.76R · PF 5.23 · t=5.0 | 19 işlem · +0.73R · toplam +14R · düşüş %2.5 · sermaye 1146$ |
| breakout | 255 · kazanma %42 · +1.77R · PF 4.52 · t=4.0 | 54 · kazanma %56 · +1.56R · PF 5.30 · t=3.1 | 4 işlem · +2.07R · toplam +8R · düşüş %0.0 · sermaye 1085$ |
| breakdown | 22 · kazanma %45 · -0.17R · PF 0.54 · t=-1.2 | 176 · kazanma %44 · +0.04R · PF 1.09 · t=0.5 | 14 işlem · +0.16R · toplam +2R · düşüş %2.6 · sermaye 1022$ |
| pullback_s | 95 · kazanma %61 · +0.34R · PF 2.11 · t=3.1 | 469 · kazanma %50 · +0.02R · PF 1.04 · t=0.4 | 114 işlem · -0.04R · toplam -5R · düşüş %15.3 · sermaye 948$ |
| **breakout+breakdown** | 277 · kazanma %42 · +1.61R · PF 4.28 · t=4.0 | 230 · kazanma %47 · +0.40R · PF 1.96 · t=2.8 | 18 işlem · +0.59R · toplam +11R · düşüş %2.6 · sermaye 1109$ |
| **hepsi** | 778 · kazanma %43 · +0.59R · PF 2.26 · t=3.9 | 749 · kazanma %51 · +0.18R · PF 1.45 · t=3.4 | 81 işlem · +0.15R · toplam +12R · düşüş %13.7 · sermaye 1119$ |
| **pullback+breakout** | 661 · kazanma %41 · +0.65R · PF 2.32 · t=3.7 | 104 · kazanma %64 · +1.18R · PF 5.28 · t=4.3 | 4 işlem · +2.07R · toplam +8R · düşüş %0.0 · sermaye 1085$ |

Yıllara göre (tüm sinyaller):

| Aile | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|
| pullback | işlem yok | 140 · kazanma %41 · -0.06R · PF 0.87 · t=-0.7 | 266 · kazanma %39 · -0.06R · PF 0.88 · t=-0.9 | 50 · kazanma %74 · +0.76R · PF 5.23 · t=5.0 |
| breakout | işlem yok | 80 · kazanma %51 · +4.26R · PF 10.26 · t=3.6 | 175 · kazanma %38 · +0.63R · PF 2.20 · t=2.0 | 54 · kazanma %56 · +1.56R · PF 5.30 · t=3.1 |
| breakdown | işlem yok | işlem yok | 41 · kazanma %24 · -0.48R · PF 0.18 · t=-5.2 | 157 · kazanma %49 · +0.15R · PF 1.39 · t=1.6 |
| pullback_s | işlem yok | işlem yok | 137 · kazanma %58 · +0.27R · PF 1.86 · t=3.1 | 427 · kazanma %50 · +0.01R · PF 1.02 · t=0.2 |

## Dayanıklılık (06.10.2026) ve karar

| Kontrol | Eğitim | Test |
|---|---|---|
| Sadece 12 büyük coin (hayatta kalma yanlılığı az) | 204 · +1.61R · t=3.2 | 32 · +0.24R · t=1.0 |
| Büyükler hariç 14 coin | 168 · +1.35R · t=3.6 | 62 · +1.90R · t=3.7 |
| Kırılım 10/20/55 gün × iz 3–4 ATR (12 büyük coin) | hepsi +1.1…+2.0R | hepsi +0.24…+0.35R |
| İz 2 ATR | +0.4…+0.8R | −0.10…+0.05R (çöker) |
| Hesap: %0.5 risk, max 6 açık (tüm coin) | 80 işlem · +0.86R · düşüş %7.6 · +%39 | 13 işlem · +2.50R · düşüş %0.5 · +%17 |

- Sinyaller aynı günlerde kümelenir (tek günde 15'e kadar) → t-istatistikleri iyimser; gerçek bağımsız örnek daha az.
- Altcoin sonuçları hayatta kalma yanlılığı içerir (evren bugünkü hacim listesi). Büyük coinlerde beklenen avantaj
  mütevazı (~+0.2–0.3R/işlem). Strateji kazancını az sayıda büyük trendden alır; kayıp serileri normaldir.
- **Karar:** canlıya sadece `breakout` (20g, hacim 1.3×, stop 2 ATR, iz 3 ATR, %0.5 risk, max 6) + aşağıdaki sıkışma filtresi. pullback (eğitimde
  negatif), breakdown ve pullback_s (testte ~0) eklenmedi. Canlı sonuçlar tracking/trend_results.csv'de izlenir.

## Sıkışma filtresi (06.10.2026) — canlıda açık

Kırılımdan önceki gün ATR/fiyat, son 120 günün yüzdelik sırasında 0.5'in altında olmalı (volatilite sıkışmasından çıkış).
Diğer filtreler (BTC'ye göre güç, güçlü kapanış, aşırı uzama, 7g getiri, BTC net yükseliş) eğitim ve testte tutarlı
iyileştirme göstermedi → eklenmedi.

| Eşik | Tüm coin eğitim | Tüm coin test | Büyük coin eğitim | Büyük coin test |
|---|---|---|---|---|
| filtresiz | 372 · +1.49R | 94 · +1.34R | 204 · +1.61R | 32 · +0.24R |
| < 0.3 | 207 · +1.38R | 30 · +1.26R | 121 · +1.52R | 11 · +1.02R |
| < 0.4 | 233 · +1.60R | 38 · +1.44R | 136 · +1.83R | 14 · +0.92R |
| **< 0.5** | **255 · +1.77R** | **54 · +1.56R** | **148 · +1.98R** | **22 · +0.55R** |
| < 0.6 | 275 · +1.65R | 65 · +1.35R | 160 · +1.77R | 26 · +0.44R |
| < 0.7 | 286 · +1.68R | 80 · +1.36R | 163 · +1.72R | 28 · +0.34R |

Hesap kurallarıyla (%0.5 risk, max 6 açık, 26 coin, ~2 yıl): filtresiz 93 işlem · +1.09R · düşüş %7.6 · 1000$ → 1626$;
**sıkışma filtreli 74 işlem · %47 kazanma · +1.85R · en büyük düşüş %4.6 · en kötü seri 7 kayıp · 1000$ → 1875$.**
R dağılımı: medyan −0.44R; kârın %74'ü en iyi %10 işlemden gelir → sinyal atlamak ya da erken çıkmak avantajı yok eder.
Not: test döneminde BTC çoğu zaman düşüş trendindeydi, long kırılım fırsatı az oldu (rejim filtresi beklendiği gibi çalıştı).
