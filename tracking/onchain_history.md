# Geçmiş on-chain analizi — 29.09.2026 12:38

- 12 token, 20661 gözlem (4 saatte bir), eğitim/test ayrımı 03.06.2026
- Skor: canlıdakiyle aynı (son 24s borsa net akışı ÷ %5 × 24s hacim, ±100). + = borsadan çıkış (birikim)

## Tahmin gücü (sıra korelasyonu, + = skor doğru yönü gösteriyor)

| | 24s sonrası | 72s sonrası | gözlem |
|---|---|---|---|
| Eğitim | -0.019 | +0.007 | 12393 |
| Test | +0.027 | +0.035 | 8268 |
| Tümü | +0.002 | +0.023 | 20661 |

| Token | 24s | 72s | gözlem | kapsam başlangıcı |
|---|---|---|---|---|
| AAVE | +0.021 | -0.027 | 1642 | 25.12.2025 |
| ENA | -0.012 | +0.085 | 1600 | 01.01.2026 |
| FET | -0.019 | +0.025 | 2165 | 29.09.2025 |
| FLOKI | +0.019 | +0.043 | 2165 | 29.09.2025 |
| LDO | +0.047 | +0.056 | 2165 | 29.09.2025 |
| LINK | -0.031 | -0.108 | 969 | 16.04.2026 |
| ONDO | +0.021 | +0.070 | 1630 | 27.12.2025 |
| PEPE | -0.045 | -0.025 | 1389 | 05.02.2026 |
| POL | -0.073 | -0.040 | 2165 | 29.09.2025 |
| SHIB | +0.119 | +0.075 | 1188 | 11.03.2026 |
| UNI | +0.011 | +0.043 | 1418 | 01.02.2026 |
| WLD | -0.056 | -0.033 | 2165 | 29.09.2025 |

## Uç skorlardan sonra ortalama getiri (%)

| Skor | 24s | 72s | gözlem |
|---|---|---|---|
| ≥ +50 (güçlü çıkış) | +0.07 | +0.49 | 7148 |
| −50…+50 | +0.05 | -0.11 | 7260 |
| ≤ −50 (güçlü giriş) | +0.05 | +0.02 | 6253 |

## Backtest (sadece on-chain tokenları + BTC, 30.09.2025 → bugün, 20661 anlık görüntüde skor var)

| Ayar seti | Eğitim | Test |
|---|---|---|
| eşik 65/35 · R:R≥2.5 · rejim · limit · 72s · on-chain 0 | 48 işlem · %38 · +0.18R · toplam +9R · düşüş %9 | 29 işlem · %38 · +0.73R · toplam +21R · düşüş %6 |
| eşik 65/35 · R:R≥2.5 · rejim · limit · 72s · on-chain 10 | 47 işlem · %34 · +0.12R · toplam +5R · düşüş %9 | 26 işlem · %35 · +0.61R · toplam +16R · düşüş %6 |
| eşik 65/35 · R:R≥2.5 · rejim · limit · 72s · on-chain 20 | 46 işlem · %33 · +0.06R · toplam +3R · düşüş %10 | 26 işlem · %35 · +0.57R · toplam +15R · düşüş %9 |
| eşik 65/35 · R:R≥2.5 · rejim · limit · 72s · on-chain 30 | 54 işlem · %30 · -0.03R · toplam -2R · düşüş %13 | 27 işlem · %33 · +0.51R · toplam +14R · düşüş %9 |
| eşik 70/30 · R:R≥2.5 · rejim · limit · 72s · on-chain 0 | 33 işlem · %36 · +0.17R · toplam +6R · düşüş %8 | 21 işlem · %38 · +0.97R · toplam +20R · düşüş %6 |
| eşik 70/30 · R:R≥2.5 · rejim · limit · 72s · on-chain 10 | 31 işlem · %32 · +0.03R · toplam +1R · düşüş %9 | 20 işlem · %35 · +0.72R · toplam +14R · düşüş %6 |
| eşik 70/30 · R:R≥2.5 · rejim · limit · 72s · on-chain 20 | 30 işlem · %37 · +0.11R · toplam +3R · düşüş %7 | 22 işlem · %36 · +0.67R · toplam +15R · düşüş %8 |
| eşik 70/30 · R:R≥2.5 · rejim · limit · 72s · on-chain 30 | 38 işlem · %32 · -0.02R · toplam -1R · düşüş %10 | 23 işlem · %35 · +0.61R · toplam +14R · düşüş %8 |
