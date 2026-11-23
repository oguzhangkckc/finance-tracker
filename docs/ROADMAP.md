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
SQLite şeması ve repository'ler, Decimal gidiş-dönüş testleri; ft config apply, ft tx add, CSV içe aktarma, ft price set, ft doctor; GVK geçici 67 FIFO doğrulaması.
Geliştirme kapısı: İşlemler girilip herhangi bir tarihteki değer görülebiliyor.
Not: Migration çalıştırıcısına tablo yeniden kurma desteği: `-- finans: foreign_keys=off` başlığı, transaction öncesinde FK kapatma, COMMIT öncesi `foreign_key_check`, ardından FK açma (K-33).

## M3 · Veri kaynakları
TEFAS ve EVDS3 adapter'ları (ilk iş: EVDS3 anahtar iletimi), backfill, veri kalitesi kontrolleri; kayıtlı fixture'larla kontrat testleri, haftalık canlı smoke testi.
Geliştirme kapısı: Kontrat testleri yeşil; backfill ile geçmiş dönem mutabakatı ±0,01 TL/kalem.
Not: JSON her yerde `json.loads(..., parse_float=Decimal)` ile ayrıştırılır; `response.json()` kullanılmaz; çok basamaklı fiyatla kontrat testi yazılır (K-32).
Not: TÜFE 2025=100 serisi tüm geçmişiyle doğrudan çekilir; ilk işlerden biri EVDS3'te bu geçmişin bulunduğunu doğrulamak. `chain_link` yedek olarak kalır (K-43).
Kabul kapısı: Bir ay canlı veri; elle tutulan tabloyla mutabakat ±0,01 TL/kalem.

## M4 · Rapor ve bildirim (ilk kullanılabilir sürüm)
Report modeli, metin ve JSON render, aylık raporda XIRR ve yalnızca katkıyla dengeleme, Telegram (rapor botu), uyarı tekilleştirme; systemd timer'ları, job_run, dead man's switch, yedekleme.
Geliştirme kapısı: Snapshot ve iş testleri yeşil; zamanlayıcılar test ortamında doğrulandı.
Kabul kapısı: İki hafta kesintisiz ve doğru rapor.
Not: Para ağırlıklı getirinin kökü [−0,99; 10] dışındaysa (alt ya da üst) rapor basit getiriyi ve "Zamanlama nedeniyle para ağırlıklı getiri anlamlı değil." notunu gösterir; domain sonuç türü bu durumu "hesaplanamadı"dan ayırır (K-44).

## M5 · OpenClaw ve güvenlik sertleştirmesi
JSON anlık görüntüleri ve rrsync ile aktarımı (yalnızca çekirdekten dışarı), ft-agent (boru hattı ve veri tazeliği için iki ayrı bayatlık sinyali), JSON Schema kontratı, SKILL.md, PPK özeti akışı (oranlar kodla çıkarılır), asistan botu; iki makine, ayrı OS kullanıcıları, systemd sertleştirme, LoadCredential, makine bazında egress allowlist.
Geliştirme kapısı: Güvenlik kontrol listesi tamam; OpenClaw makinesinde veritabanı ve çekirdek sırrı yok; ajanın yazma denemesi reddediliyor.

## M6 · İleri (ihtiyaç doğarsa)
Reel XIRR geçmişi, satışlı dengeleme önerisi (FR-15), stopaj hesabı; ek işlem türleri (temettü, bölünme, birleşme), ek veri kaynakları ve bildirim kanalları.
