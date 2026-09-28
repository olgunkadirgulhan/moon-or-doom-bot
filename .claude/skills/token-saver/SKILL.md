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
