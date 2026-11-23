# Yol haritası
Her milestone ayrı PR. Kapı geçilmeden sonrakine başlanmaz.

## M0 · İskelet
uv projesi, ruff, mypy --strict, import-linter, pre-commit, CI; migration çalıştırıcı, settings, Clock port'u, boş katmanlar.
Kapı: CI yeşil; boş katmanlar import kurallarını geçiyor.

## M1 · Domain
Modeller, FIFO lotlar, as-of değerleme, Fisher, lot reel getirisi; dağılım, sapma, histerezis; TWR ve XIRR referans testleriyle.
Kapı: Excel referans vakaları geçiyor; domain kapsamı %95+.

## M2 · Kalıcılık ve CLI
SQLite şeması ve repository'ler, Decimal gidiş-dönüş testleri; ft tx add, CSV içe aktarma, ft price set, ft doctor.
Kapı: İşlemler girilip herhangi bir tarihteki değer görülebiliyor.

## M3 · Veri kaynakları
TEFAS ve EVDS adapter'ları, backfill, veri kalitesi kontrolleri; kayıtlı fixture'larla kontrat testleri, haftalık canlı smoke testi.
Kapı: Bir ay canlı veri; elle tutulan tabloyla mutabakat tam.

## M4 · Rapor ve bildirim (ilk kullanılabilir sürüm)
Report modeli, metin ve JSON render, Telegram, uyarı tekilleştirme; systemd timer'ları, job_run, dead man's switch, yedekleme.
Kapı: İki hafta kesintisiz ve doğru rapor.

## M5 · OpenClaw ve güvenlik sertleştirmesi
ft-agent, JSON Schema kontratı, SKILL.md, PPK özeti akışı; ayrı OS kullanıcıları, systemd sertleştirme, egress allowlist.
Kapı: Güvenlik kontrol listesi tamam; ajanın yazma denemesi reddediliyor.

## M6 · İleri (ihtiyaç doğarsa)
Reel XIRR geçmişi, satışlı dengeleme önerisi, stopaj hesabı; ek veri kaynakları ve bildirim kanalları.