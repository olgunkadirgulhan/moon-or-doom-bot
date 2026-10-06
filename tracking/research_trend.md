# Trend aileleri araştırması

- 26 coin · eğitim/test ayrımı 2025-12-13T00:30:00 · komisyon %0.1 + kayma %0.05 · hesap: %1.0 risk, max 3 açık

| Aile | Eğitim (tüm sinyaller) | Test (tüm sinyaller) | Test (hesap kurallarıyla) |
|---|---|---|---|
| pullback | 406 · kazanma %40 · -0.06R · PF 0.88 · t=-1.1 | 50 · kazanma %74 · +0.76R · PF 5.23 · t=5.0 | 19 işlem · +0.73R · toplam +14R · düşüş %2.5 · sermaye 1146$ |
| breakout | 372 · kazanma %40 · +1.49R · PF 3.85 · t=4.7 | 94 · kazanma %50 · +1.34R · PF 4.52 · t=3.7 | 4 işlem · +2.07R · toplam +8R · düşüş %0.0 · sermaye 1085$ |
| breakdown | 22 · kazanma %45 · -0.17R · PF 0.54 · t=-1.2 | 176 · kazanma %44 · +0.04R · PF 1.09 · t=0.5 | 14 işlem · +0.16R · toplam +2R · düşüş %2.6 · sermaye 1022$ |
| pullback_s | 95 · kazanma %61 · +0.34R · PF 2.11 · t=3.1 | 469 · kazanma %50 · +0.02R · PF 1.04 · t=0.4 | 114 işlem · -0.04R · toplam -5R · düşüş %15.3 · sermaye 948$ |
| **breakout+breakdown** | 394 · kazanma %41 · +1.40R · PF 3.71 · t=4.6 | 270 · kazanma %46 · +0.49R · PF 2.20 · t=3.5 | 18 işlem · +0.59R · toplam +11R · düşüş %2.6 · sermaye 1109$ |
| **hepsi** | 895 · kazanma %42 · +0.63R · PF 2.31 · t=4.5 | 789 · kazanma %50 · +0.23R · PF 1.56 · t=3.9 | 81 işlem · +0.15R · toplam +12R · düşüş %13.7 · sermaye 1119$ |
| **pullback+breakout** | 778 · kazanma %40 · +0.68R · PF 2.36 · t=4.3 | 144 · kazanma %58 · +1.14R · PF 4.67 · t=4.7 | 4 işlem · +2.07R · toplam +8R · düşüş %0.0 · sermaye 1085$ |

Yıllara göre (tüm sinyaller):

| Aile | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|
| pullback | işlem yok | 140 · kazanma %41 · -0.06R · PF 0.87 · t=-0.7 | 266 · kazanma %39 · -0.06R · PF 0.88 · t=-0.9 | 50 · kazanma %74 · +0.76R · PF 5.23 · t=5.0 |
| breakout | işlem yok | 153 · kazanma %50 · +2.86R · PF 7.28 · t=4.3 | 219 · kazanma %34 · +0.54R · PF 1.94 · t=2.0 | 94 · kazanma %50 · +1.34R · PF 4.52 · t=3.7 |
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
- **Karar:** canlıya sadece `breakout` (20g, hacim 1.3×, stop 2 ATR, iz 3 ATR, %0.5 risk, max 6). pullback (eğitimde
  negatif), breakdown ve pullback_s (testte ~0) eklenmedi. Canlı sonuçlar tracking/trend_results.csv'de izlenir.
