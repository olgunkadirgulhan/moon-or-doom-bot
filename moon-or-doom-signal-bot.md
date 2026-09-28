# Moon or Doom — Kişisel Telegram Sinyal Botu (Spec)

> Bu dosya Claude Code için yazıldı. Repo: `moon-or-doom` (mevcut 4H destek/direnç YouTube otomasyonu burada).
> Amaç: Mevcut S/R mantığını yeniden kullanarak **sadece bana özel** bir Telegram botu yapmak.
> ⚠️ Kişisel araçtır, yatırım tavsiyesi değildir. Bot emir göndermez, sadece analiz yapar.

---

## 0. Claude Code için ilk talimat

1. Önce aşağıdaki **Bölüm 9'daki skill'i** `.claude/skills/token-saver/SKILL.md` olarak oluştur ve kurallarına uy.
2. Repo'da sadece `grep`/`glob` ile S/R hesaplayan modülü bul (`support`, `resistance`, `pivot`, `4h` anahtar kelimeleri). Tüm repoyu okuma.
3. O modülü `core/levels.py` altına taşı/sar; YouTube kısmına dokunma.
4. Bölüm 8'deki fazları sırayla uygula, her faz sonunda kısa özet ver.

---

## 1. Özellikler (kapsam)

| # | Özellik | Detay |
|---|---------|-------|
| 1 | Çoklu zaman dilimi | 1h, 4h, 8h, 1d destek/direnç |
| 2 | Sinyal | AL / SAT / BEKLE + güven skoru (0–100) |
| 3 | İşlem seviyeleri | Giriş, Stop Loss, TP1, TP2, Risk/Ödül oranı |
| 4 | On-chain akış | Etherscan, BscScan, PolygonScan vb. → borsa giriş/çıkış (netflow) + balina transferleri |
| 5 | Grafik | Her coin için 2×2 grafik (4 TF) + seviyeler + netflow alt paneli |
| 6 | Özet liste | **En az 10 coin**, alt alta, **skora göre azalan sırada** (en çok önerilen en üstte), tablo görseli |
| 7 | Gizlilik | Sadece benim `chat_id`'me cevap verir, diğerlerini yok sayar |
| 8 | Zamanlama | **Günde 4 otomatik rapor** + manuel komutlar |
| 9 | Format | **Video YOK.** Sadece PNG grafik ve çizelge (tablo) görselleri |

---

## 2. Teknoloji

- **Python 3.11+**
- `python-telegram-bot` v21 (async) — bot
- `ccxt` — OHLCV verisi (Binance; 1h/4h/8h/1d native destekli)
- `pandas`, `numpy`
- `ta` (veya `pandas-ta`) — RSI, EMA, ATR
- `mplfinance` + `matplotlib` — mum grafikleri ve tablo görseli
- `httpx` — scan API çağrıları (async)
- `APScheduler` — saatlik tarama
- `SQLite` — cache + sinyal geçmişi
- `python-dotenv` — anahtarlar

---

## 3. Klasör yapısı

```
moon-or-doom/
├── bot/
│   ├── main.py            # Telegram bot + scheduler başlatma
│   ├── handlers.py        # /scan /coin /list /watch /settings
│   └── auth.py            # chat_id whitelist decorator
├── core/
│   ├── data.py            # ccxt OHLCV çekme + SQLite cache
│   ├── levels.py          # Destek/direnç (mevcut 4H mantığı buraya)
│   ├── indicators.py      # EMA50/200, RSI14, ATR14, hacim
│   ├── onchain.py         # Scan API'leri → netflow, balina
│   ├── signal.py          # Skor → AL/SAT/BEKLE + giriş/SL/TP
│   └── chart.py           # 2x2 grafik + özet tablo PNG
├── config/
│   ├── coins.yaml         # İzlenen coinler + kontrat adresleri + zincir
│   └── exchange_wallets.yaml  # Borsa cüzdan etiketleri
├── data/cache.db
├── .env
├── requirements.txt
└── .claude/skills/token-saver/SKILL.md
```

---

## 4. Destek / Direnç algoritması (`core/levels.py`)

1. Mevcut repodaki 4H fonksiyonu **baz alınır**, TF parametresi eklenir.
2. Swing high/low tespiti: fraktal pencere (1h:5, 4h:3, 8h:3, 1d:2 mum sağ/sol).
3. Yakın seviyeleri birleştir: tolerans = `0.5 × ATR14`.
4. Güç skoru = dokunma sayısı + hacim ağırlığı + yakınlık (son mumlar daha değerli).
5. Her TF için fiyatın altında en güçlü 3 destek, üstünde en güçlü 3 direnç döner.
6. **Konfluens:** Birden fazla TF'de çakışan seviye → "güçlü seviye" olarak işaretlenir (grafikte kalın çizgi).

Çıktı:
```python
{"tf": "4h", "supports": [(price, strength), ...], "resistances": [...]}
```

---

## 5. On-chain akış (`core/onchain.py`)

**API:** Etherscan API V2 — tek API key ile çoklu zincir (`chainid` parametresi).
> Not: BscScan/PolygonScan ayrı API'leri V2'ye taşındı; uygulamadan önce güncel dokümanı kontrol et: https://docs.etherscan.io

| Zincir | chainid |
|--------|---------|
| Ethereum | 1 |
| BSC | 56 |
| Polygon | 137 |
| Arbitrum | 42161 |
| Base | 8453 |
| Optimism | 10 |

**Mantık:**
- `module=account&action=tokentx&contractaddress=...` ile son 24s/7g token transferleri.
- `exchange_wallets.yaml` içindeki borsa adresleriyle eşleştir:
  - Borsaya **giriş** (inflow) → satış baskısı (negatif)
  - Borsadan **çıkış** (outflow) → birikim (pozitif)
- `netflow = outflow − inflow` (USD cinsinden)
- **Balina:** tek transfer > coin'in 24s hacminin %0.5'i veya > $250k
- Skor: −100 … +100
- Rate limit: 5 çağrı/sn (free) → `asyncio.Semaphore(4)` + SQLite cache (TTL 15 dk)
- Native coinler (BTC, SOL vb. EVM olmayan) için on-chain adımı atlanır, skor = 0, grafikte "on-chain yok" yazar.

Borsa cüzdan etiketleri için açık kaynak kaynak: `brianleect/etherscan-labels` (GitHub) → sadece büyük borsaları (Binance, Coinbase, OKX, Bybit, Kraken) `exchange_wallets.yaml`'a aktar.

---

## 6. Sinyal motoru (`core/signal.py`)

**Skor bileşenleri (ağırlıklar config'den ayarlanabilir):**

| Bileşen | Ağırlık | AL yönü |
|---------|---------|---------|
| Trend (EMA50 > EMA200, 4h+1d) | 25 | Yukarı trend |
| Seviyeye yakınlık | 25 | Fiyat güçlü desteğe < 1 ATR |
| RSI14 (1h+4h) | 15 | 30–45 arası ve yukarı dönüyor |
| Çoklu TF konfluens | 15 | Destek ≥2 TF'de çakışıyor |
| On-chain netflow | 20 | Pozitif netflow / borsadan çıkış |

- Toplam ≥ 65 → **AL**, ≤ 35 → **SAT**, arası → **BEKLE**

**İşlem seviyeleri (AL için; SAT tersi):**
- **Giriş:** en yakın güçlü destek (veya mevcut fiyat, desteğe < 0.3 ATR ise)
- **Stop Loss:** destek − `1.0 × ATR14(4h)`
- **TP1:** ilk direnç
- **TP2:** ikinci direnç (veya 1d direnci)
- **R:R** = (TP1 − giriş) / (giriş − SL) → **< 1.5 ise listeden çıkarılmaz**, "⚠️ R:R düşük" etiketiyle gösterilir ve skordan 10 puan düşülür (liste her zaman ≥10 coin kalsın)

**Evren:** İzleme listesi en az 30 coin (Binance USDT paritelerinde 24s hacme göre ilk 30 + `coins.yaml`'daki manuel eklemeler). Rapora bunlardan skoru en yüksek **ilk 10+** coin girer.

---

## 7. Grafikler (`core/chart.py`) ve Telegram çıktısı

### 7.1 Coin grafiği (her önerilen coin için 1 PNG)
- 2×2 ızgara: 1h | 4h / 8h | 1d
- Mumlar + EMA50/200
- Destek: yeşil yatay çizgi, direnç: kırmızı; konfluens seviyeleri kalın
- Giriş: mavi kesikli, SL: kırmızı kesikli, TP1/TP2: yeşil kesikli (fiyat etiketli)
- Alt panel (4h grafiğinde): günlük on-chain netflow barları (yeşil/kırmızı)
- Başlık: `ETH — AL — Skor 72 — R:R 2.3`
- Koyu tema, 1600×1200 px

### 7.2 Özet tablo görseli (alt alta liste)
Tek PNG, **en az 10 satır**, **skora göre büyükten küçüğe** sıralı (1. sıra = en güçlü öneri):

| # | Coin | Sinyal | Skor | Giriş | SL | TP1 | TP2 | R:R | Netflow 24s |
|------|--------|------|-------|----|-----|-----|-----|-------------|
| 1 | ETH | 🟢 AL | 72 | 2450 | 2380 | 2560 | 2680 | 2.3 | +$4.1M |
| ... | | | | | | | | |

### 7.3 Telegram komutları
| Komut | İş |
|-------|-----|
| `/scan` | Tüm izleme listesini tara → önce özet tablo, sonra her AL/SAT coin için grafik |
| `/coin ETH` | Tek coin detay grafiği + metin özet |
| `/list` | İzleme listesini göster |
| `/watch add PEPE` / `/watch rm PEPE` | Listeyi düzenle |
| `/settings` | Eşik skorları, R:R minimum, tarama sıklığı |

- **Otomatik rapor: günde 4 kez**, İstanbul saatiyle **00:00, 06:00, 12:00, 18:00** (`APScheduler` cron, `timezone="Europe/Istanbul"`; saatler `/settings` ile değiştirilebilir, minimum 4).
- Her raporda gönderim sırası:
  1. Özet tablo PNG (≥10 coin, skor azalan)
  2. Listedeki her coin için 2×2 grafik PNG, **aynı sırayla** (Telegram `send_media_group` ile 10'arlı albüm)
- Video, animasyon veya ses **üretilmez**; YouTube otomasyon kodu bu bota import edilmez.
- Raporlar arası: sadece SL'ye veya TP'ye değen coin için kısa uyarı mesajı (opsiyonel, varsayılan kapalı).
- **Gizlilik:** `auth.py` decorator → `update.effective_chat.id != ALLOWED_CHAT_ID` ise sessizce yok say.

### 7.4 `.env`
```
TELEGRAM_BOT_TOKEN=
ALLOWED_CHAT_ID=
ETHERSCAN_API_KEY=
EXCHANGE=binance
```

---

## 8. Uygulama fazları

1. **Faz 1 – Veri + seviyeler:** `data.py`, `levels.py` (repodaki 4H kodundan), `indicators.py`. Test: BTC için 4 TF seviyeleri konsola yazdır.
2. **Faz 2 – Grafik:** `chart.py` 2×2 grafik + özet tablo PNG. Test: `data/test_btc.png`.
3. **Faz 3 – Sinyal:** `signal.py` (on-chain skoru şimdilik 0).
4. **Faz 4 – Telegram:** `main.py`, `handlers.py`, `auth.py`, scheduler.
5. **Faz 5 – On-chain:** `onchain.py` + `exchange_wallets.yaml`, sinyale bağla, grafiğe netflow paneli ekle.
6. **Faz 6 – Sağlamlaştırma:** hata yönetimi, API rate limit, systemd/Docker ile 7/24 çalıştırma.

---

## 9. Token tasarrufu skill'i

`.claude/skills/token-saver/SKILL.md` olarak oluştur:

```markdown
---
name: token-saver
description: Bu repoda her görevde uygula. Dosya okuma, arama ve cevap uzunluğunu minimumda tutarak token tasarrufu sağlar.
---

# Token Saver

## Okuma
- Tüm repoyu asla okuma. Önce Grep/Glob ile hedef dosyayı bul.
- Dosyanın sadece gerekli bölümünü oku (offset/limit). 300 satırdan uzun dosyayı tam okuma.
- Aynı dosyayı bir oturumda iki kez okuma; düzenlediğin dosyayı doğrulamak için tekrar okuma.
- `data/`, `*.db`, `*.png`, `node_modules/`, `.venv/`, log dosyalarını okuma.

## Yazma
- Küçük değişikliklerde Edit kullan, dosyayı baştan yazma.
- Yeni dosyaları tek seferde tam yaz, parça parça yeniden yazma.
- Açıklama yorumu minimum; docstring tek satır.

## Komutlar
- Test çıktısını `| tail -30` ile kısalt.
- `pip install` çıktısını `-q` ile sessiz çalıştır.
- Uzun JSON/API cevaplarını dosyaya yaz, sadece ilgili alanı `jq`/python ile göster.

## Cevap
- Faz sonunda en fazla 5 madde özet: ne yapıldı, hangi dosyalar, sıradaki adım.
- Kod bloğunu cevapta tekrar gösterme; dosya yolunu söyle.
- Plan onayı isteme, net görevde direkt uygula. Sadece geri alınamaz işlemde sor.

## Bağlam
- Bu spec dosyası (`moon-or-doom-signal-bot.md`) tek kaynak. Gerekince sadece ilgili bölümü oku.
- Faz bitince `PROGRESS.md`'ye 1 satır ekle; yeni oturumda önce onu oku.
```

---

## 10. Faydalı açık kaynak repolar

| Repo | Ne için |
|------|---------|
| `ccxt/ccxt` | Borsa OHLCV verisi |
| `python-telegram-bot/python-telegram-bot` | Bot altyapısı |
| `matplotlib/mplfinance` | Mum grafikleri, yatay seviye çizgileri |
| `bukosabino/ta` (veya `twopirllc/pandas-ta`) | RSI, EMA, ATR |
| `freqtrade/freqtrade` | Strateji/sinyal mantığı referansı (sadece fikir için, kurulum gerekmez) |
| `brianleect/etherscan-labels` | Borsa cüzdan adres etiketleri |

> Claude Code: Bu repoları klonlama, sadece pip paketi olarak kullan. `freqtrade` ve `etherscan-labels` sadece referans; gerekirse tek dosyayı WebFetch ile oku.

---

## 11. Kabul kriterleri

- [ ] `/scan` 60 sn içinde özet tablo + grafikler gönderiyor
- [ ] Her grafikte 4 TF, S/R, giriş, SL, TP1/TP2 görünüyor
- [ ] Her raporda en az 10 coin var, skora göre azalan sırada
- [ ] Günde 4 rapor (00/06/12/18 İstanbul) otomatik geliyor
- [ ] Sadece PNG grafik/tablo gönderiliyor, video yok
- [ ] R:R < 1.5 olanlar ⚠️ etiketli
- [ ] EVM coinlerde netflow paneli dolu
- [ ] Başka bir kullanıcı bota yazınca cevap yok
