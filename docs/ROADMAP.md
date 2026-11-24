# Yol haritası
Her milestone ayrı branch ve ayrı PR. İki tür kapı vardır (DESIGN.md, K-19):
- **Geliştirme kapısı:** CI ve testlerle ölçülür; geçilmeden sonraki milestone'un geliştirmesine başlanmaz.
- **Kabul kapısı:** takvime bağlıdır; sonraki milestone'un geliştirmesini bekletmez, ama o milestone canlıya alınmadan önce geçilmiş olmalıdır.

## M0 · İskelet
uv projesi (Python 3.13), ruff, mypy --strict, import-linter ve AST mimari testleri, pre-commit, CI (pip-audit dahil); bağlantı fabrikası ve migration çalıştırıcı, settings, Clock port'u, contracts dahil boş katmanlar, CLAUDE.md.
Geliştirme kapısı: CI yeşil; boş katmanlar import kurallarını ve mimari testlerini geçiyor; migration çalıştırıcı testleri yeşil.

## M1 · Domain
Modeller, FIFO lotlar, as-of değerleme, Fisher, TÜFE referans ay kuralı ve 2003=100'den 2025=100'e zincirleme, lot reel getirisi; dağılım, sapma, histerezis, yalnızca katkıyla dengeleme; fon TWR'ı (fiyat oranı) ve XIRR (bir yıldan kısa dönemde yıllıklandırılmamış) referans testleriyle.
Geliştirme kapısı: Excel referans vakaları göreli 1e-6 / mutlak 1e-8 toleransla geçiyor (K-38); zincirlenmiş TÜFE'den hesaplanan yıllık oranlar TÜİK'in yayımladığı oranlarla eşleşiyor (K-40); domain kapsamı %95+.
İlk commit (M0 düzeltmeleri): `transaction()` COMMIT hata verirse ROLLBACK yapar (K-34); duvar saati dedektörüne `time.localtime`, `time.gmtime`, `time.ctime` ve zaman argümansız `time.strftime` eklenir (K-35).
Not: Domain `localcontext`'inde `decimal.FloatOperation` trap'i açık; testlerde conftest ile global açık (K-31).

## M2 · Kalıcılık ve CLI
SQLite şeması ve repository'ler, Decimal gidiş-dönüş testleri; ft config apply, ft tx add, CSV içe aktarma, ft price set, ft tx void, ft value, ft doctor; GVK geçici 67 FIFO doğrulaması (yapıldı, K-54).
Geliştirme kapısı: İşlemler girilip herhangi bir tarihteki değer görülebiliyor.
Not: Migration çalıştırıcısına tablo yeniden kurma desteği: `-- finans: foreign_keys=off` başlığı, transaction öncesinde FK kapatma, COMMIT öncesi `foreign_key_check`, ardından FK açma (K-33).
Not: Config doğrulaması bütün hataları tek seferde, yer, değer, beklenen ve düzeltme önerisiyle gösterir (K-47).
Not: 0001 yalnızca instrument, txn, price, price_revision (K-49). İşlem iptali `ft tx void` (K-48); CSV içe aktarma kuralları (K-50); pasif enstrüman kuralları ve uyarıları (K-51); codec ve tarih kısıtları (K-52).
Not: Bekleyen migration varsa önce SQLite backup API'siyle yerel kopya alınır; son 5 kopya tutulur, yedek alınamazsa migration uygulanmaz (K-55).

## M3 · Veri kaynakları
EVDS3 ve TEFAS adapter'ları (TEFAS isteklerini kullanıcı çalıştırır, K-71), TEFAS fonlarına elle fiyat, veri kalitesi kontrolleri; kayıtlı fixture'larla kontrat testleri, haftalık canlı smoke testi.
Geliştirme kapısı: Kontrat testleri yeşil; TEFAS'tan çekilen fiyat geçmişiyle geçmiş dönem mutabakatı ±0,01 TL/kalem (`ft reconcile`).
İlk commit (M2 düzeltmeleri): migration atomikliğinin grup bazında olduğu açıkça yazıldı; yedeklemede eski `.partial` artıkları temizlenir (K-57); alış iptali reddedilince önce iptal edilecek satışlar listelenir (K-58).
Not: JSON her yerde `json.loads(..., parse_float=Decimal)` ile ayrıştırılır; `response.json()` kullanılmaz; çok basamaklı fiyatla kontrat testi yazılır (K-32).
Not: TÜFE 2025=100 serisi tüm geçmişiyle doğrudan çekilir; EVDS3'te 2005-01'den itibaren bulunduğu ve eski seriyle oranın sabit olduğu canlı doğrulandı (K-43, K-70). `chain_link` yedek olarak kalır.
Not: Migration 0002: cpi, cpi_revision, raw_payload; price_revision'a kaynak kolonları (K-49, K-65). TEFAS fiyatları gelince her işlemin birim fiyatı o günün TEFAS fiyatıyla karşılaştırılır; uyuşmazlık büyük olasılıkla yanlış tarih (K-53, eşik K-64).
Not: Canlı deneme (2026-11-24): TEFAS robots.txt `/api/`'yi otomatik erişime kapatıyor; kullanıcı API'yi kendi makinesinde çalıştırmaya karar verdi, tarayıcı otomasyonu yok, engel aşılmaz (K-60, K-71); Takasbank'tan izin istenmedi (K-73). EVDS3 anahtarı başlıkta, varsayılan TLS yeterli (K-61).
Not: TEFAS JSON API'si kullanılır (K-71): `fonFiyatBilgiGetir` (periyod) ve `fonGnlBlgSiraliGetir` (≤28 gün); BYF birim pay değeri ikincisinden (K-72). Kayıtlar `tests/fixtures/tefas/`.
Not: HTTP istemci kuralları: dürüst User-Agent, robots.txt kontrolü, `Retry-After` (K-62). Mutabakat için `ft reconcile` (K-67).
Kabul kapısı: Bir ay canlı veri; elle tutulan tabloyla mutabakat ±0,01 TL/kalem.

## M4 · Rapor ve bildirim (ilk kullanılabilir sürüm)
Report modeli, metin ve JSON render, aylık raporda XIRR ve yalnızca katkıyla dengeleme, Telegram (rapor botu), uyarı tekilleştirme; systemd timer'ları, job_run, dead man's switch, yedekleme.
Geliştirme kapısı: Snapshot ve iş testleri yeşil; zamanlayıcılar test ortamında doğrulandı.
Kabul kapısı: İki hafta kesintisiz ve doğru rapor.
Not: Para ağırlıklı getirinin kökü [−0,99; 10] dışındaysa (alt ya da üst) rapor basit getiriyi ve "Zamanlama nedeniyle para ağırlıklı getiri anlamlı değil." notunu gösterir; domain sonuç türü bu durumu "hesaplanamadı"dan ayırır (K-44).
Not: Katkı tanımlı değilse aylık raporun dengeleme bölümü "Katkı tanımlı değil." yazar, sıfırlarla dolu öneri göstermez; eksik `[contribution]` 0 yerine "tanımlı değil" okunur (K-56).
Not: Katkı açıkça 0 ise dengeleme bölümü "Bu ay katkı 0." yazar; sıfırlarla dolu öneri gösterilmez (K-59).
Not: Kadans (K-73, K-69'u değiştirir): TEFAS fiyatları hafta içi her gün 21:30'da `ft sync prices` ile; dağılım sapması her başarılı senkronizasyondan sonra. Haftalık rapor isteğe bağlı, kabul süresince açık; EVDS otomatik.
Not: Dağılım dışı varlık (ör. acil durum fonu): takip edilir, dağılım, sapma ve dengelemeye girmez (K-74).
Not: Dağılım içi değer birkaç aylık katkıya (öneri 3) ulaşana kadar sapma alarmları sessiz (K-75).

## M5 · OpenClaw ve güvenlik sertleştirmesi
JSON anlık görüntüleri ve rrsync ile aktarımı (yalnızca çekirdekten dışarı), ft-agent (boru hattı ve veri tazeliği için iki ayrı bayatlık sinyali), JSON Schema kontratı, SKILL.md, PPK özeti akışı (oranlar kodla çıkarılır), asistan botu; iki makine, ayrı OS kullanıcıları, systemd sertleştirme, LoadCredential, makine bazında egress allowlist.
Geliştirme kapısı: Güvenlik kontrol listesi tamam; OpenClaw makinesinde veritabanı ve çekirdek sırrı yok; ajanın yazma denemesi reddediliyor.

## M6 · İleri (ihtiyaç doğarsa)
Reel XIRR geçmişi, satışlı dengeleme önerisi (FR-15), stopaj hesabı; ek işlem türleri (temettü, bölünme, birleşme), ek veri kaynakları ve bildirim kanalları.
