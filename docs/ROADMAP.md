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
Not: HTTP istemci kuralları: dürüst User-Agent, robots.txt kontrolü, `Retry-After` (K-62). Mutabakat için `ft reconcile` (K-67): adet, fiyat ve değer ayrı karşılaştırılır, fiyat farkında ekstrenin kullandığı fiyat günü gösterilir (K-78).
Not: `txn.unit_price_scale` (migration 0003): girilen fiyatın basamak sayısı K-64 için korunur; M4 tabloları 0004'e kayar (K-76). `ft data check --strict` uyarıda 1 ile çıkar (K-77).
Not: `make live` EVDS canlı smoke testini çalıştırır; haftalık timer M4'te. `ft doctor` son fiyat tarihlerini ve bayatlığı gösterir.
Kabul kapısı: Bir ay canlı veri; elle tutulan tabloyla mutabakat ±0,01 TL/kalem.
Not: "Bir ay canlı veri" fiyat ve TÜFE akışıyla izlenebilir; mutabakat gerçek aracı kurum ekstresi gerektirir ve sanal portföyle geçilmez (K-112).
Kabul süresi: "bir ay canlı veri" 2026-11-25 – 2026-12-25 (sanal `sync-prices`'ın ilk zamanlanmış çalışması 2026-11-25 12:15). Elle tutulan tabloyla mutabakat ilk gerçek aracı kurum ekstresini bekliyor.

## M4 · Rapor ve bildirim (ilk kullanılabilir sürüm)
Report modeli, metin ve JSON render, aylık raporda XIRR ve yalnızca katkıyla dengeleme, Telegram (rapor botu), uyarı tekilleştirme; systemd timer'ları, job_run, dead man's switch, yedekleme.
Geliştirme kapısı: Snapshot ve iş testleri yeşil; zamanlayıcılar test ortamında doğrulandı.
Kapının kanıtı: uçtan uca rapor snapshot'ları `tests/e2e`; iş yürütücü `tests/application/test_jobs.py`; birim dosyaları `tests/deploy` ve CI'daki `units` işi (`deploy/check-units.sh`, systemd-analyze calendar ve verify).
Kabul kapısı: İki hafta kesintisiz ve doğru rapor; süre, cihazda bütün zamanlayıcıların açıldığı gün başlar.
Kurulum durumu (2026-11-24): cihaz kuruldu; `ft doctor` fiyatlar dışında yeşil; `backup` ve `sync-cpi` zamanlayıcıları açık; ilk yedek Mac'e çekildi ve geri yükleme testi geçti.
Kabul süresi (sanal portföy, K-112): 2026-11-24 – 2026-12-08. İlk sanal alımlar 2026-11-24'te girildi; altı sanal zamanlayıcı da açık. Süre içinde haftalık rapor 2026-11-29 ve 2026-12-06'da, aylık rapor 2026-12-05 ile 10 arasında. Gerçek `sync-prices`, `weekly-report`, `monthly-report` ve `payday` gerçek alımlar başlayınca açılır (K-121).
Not: M4 kabulü sanal portföyle şartlı geçilebilir: sanal timer'lar iki hafta açık ve raporlar zamanında, raporlar aynı sanal işlemlerle elle tutulan tabloyla mutabık, gerçek profilin yedek ping'i hiç kaçmamış; gerçek işlemler başlayınca ilk rapor ping'i ayrıca doğrulanır (K-112).
M4 kabul süresinde yapılan değişiklik (2026-11-25, `2a6383f`): Pi #15'ten #18'e güncellendi. Rapor üretimi ve renderer kodu değişmedi; yeni olanlar web servisi ve `sync-prices`'a eklenen `--bugun`. #17 iki değişiklik getirdi: veri kalitesi denetimi raporun gününe kadarki işlemlere bakar (geçmiş tarihli raporları düzeltir); sanal önizlemede payı 0 çıkan fon görünür. Kurulumdan hemen sonra iki profilde `doctor` ve `job list` kontrol edildi. Zamanlanmış bir iş bu güncelleme yüzünden bozulursa kabul süresi düzeltme gününden yeniden başlar.
İlk commit (M3 düzeltmeleri): mutabakatta adet farkı son 5 işlem gününde girilmiş tek bir işlemle eşleşiyorsa "olası valör farkı" gösterilir (K-79).
Not: Para ağırlıklı getirinin kökü [−0,99; 10] dışındaysa (alt ya da üst) rapor basit getiriyi ve "Zamanlama nedeniyle para ağırlıklı getiri anlamlı değil." notunu gösterir; domain sonuç türü bu durumu "hesaplanamadı"dan ayırır (K-44).
Not: Katkı tanımlı değilse aylık raporun dengeleme bölümü "Katkı tanımlı değil." yazar, sıfırlarla dolu öneri göstermez; eksik `[contribution]` 0 yerine "tanımlı değil" okunur (K-56).
Not: Katkı açıkça 0 ise dengeleme bölümü "Bu ay katkı 0." yazar; sıfırlarla dolu öneri gösterilmez (K-59).
Not: Kadans (K-73, K-69'u değiştirir): TEFAS fiyatları hafta içi her gün 21:30'da `ft sync prices` ile; dağılım sapması her başarılı senkronizasyondan sonra. Haftalık rapor isteğe bağlı, kabul süresince açık; EVDS otomatik.
Not: Dağılım dışı varlık (ör. acil durum fonu): takip edilir, dağılım, sapma ve dengelemeye girmez; rapor dağılım içi, dışı ve toplam değeri ayrı gösterir; XIRR yalnızca dağılım içi, dağılım dışı varlıklar basit reel getiriyle (K-74).
Not: Dağılım içi değer 3 aylık katkıya ulaşana kadar sapma alarmları sessiz; katkı tanımlı değilse eşik 0; sessiz dönem bir kez biter ve tarihiyle kaydedilir, geri dönmez; eşik çevresinde titreşme testi (K-75).
Not: Her zaman açık Linux makine ve systemd; her iş `ft job run <iş>` ile; birim dosyaları testte ve CI'da systemd-analyze ile doğrulanır (K-80). Snapshot testleri syrupy ile; log standart `logging` ile JSON (K-81).
Not: Gece yedeği age ile birden çok açık anahtara şifreli, sunucuda yerel dizinde; şifrelemeden önce integrity_check, şifreli dosyanın sha256 özeti; Mac SSH ile çeker ve `scripts/verify_backup.sh` ile tam geri yükleme testi yapar; gizli anahtar sunucuda durmaz (K-82). Dead man's switch: rapor ve günlük yedek ping'i (K-84).
Not: Maaş günü mesajı katkının sınıf ve fon bazında dağılım önerisi ve `ft tx add` hatırlatması (K-83). Telegram'da TL tutarları varsayılan gizli (K-90); maaş günü mesajı için ayrı ayar, varsayılan gizli (K-93).
Not: Rapor kuralları: eksik fiyat açıkça yazılır ve dağılım, alarm, plan atlanır; kapsam etiketleri; aylık raporda aylık değişim; Telegram'da `<code>`; snapshot'lar uçtan uca (K-95).
Not: Fiyatlar eksikken alarm değerlendirilmez (K-85); mantıksal tarihler K-86; sessiz dönem `allocation_state`'te (K-87); haftalık değişim önceki Pazar'a göre, Modified Dietz ile (K-88, K-94).
Not: İş sonuçları: eksik fiyat ya da gönderilemeyen bildirim "partial"; aylık rapor TÜFE'yi ayın 10'una kadar bekler; ping yalnız "ok" ve "failed"da (K-96).
Not: Evdeki Debian tabanlı cihazda systemd; tek şablon servis ve iş başına timer, `deploy/ft-finans`, maaş günü 3 günlük pencere, Mac yedekleri rrsync ile çeker (K-97).
Not: Kurulumda ilk iş `ft doctor` ve `ft sync cpi` (K-91); Telegram kurulumu ve `ft notify test` kullanıcıda (K-89); M4 birimlerinde LoadCredential (K-92).
Not: Cihaz başka projelerle paylaşıldığı için M4 birimlerinde ve `deploy/ft-finans`'ta NoNewPrivileges, PrivateTmp, ProtectSystem=strict, ReadWritePaths=/var/lib/finans ve ProtectHome var; kalan risk: birim sertleştirmesi root seviyesindeki bir saldırıya karşı korumaz (K-98). Sistem saat dilimi değiştirilmez, kurulumda yalnızca NTP açılır (K-99).
Açık soru: Paylaşılan cihazın sertleştirmesi (SSH parola girişi, container portlarının bağlanması, IPv6 erişimi): gerçek işlemler girilmeden önce değerlendirilecek.

## W0 · Web ve sanal portföy için hazırlık
DESIGN'da web arayüzü ve sanal portföy (K-101…K-113). CLI'daki girdi ayrıştırması ve Türkçe sayı biçimi ortak modüllere taşınır; davranış değişmez.
Geliştirme kapısı: `make check` yeşil; CLI çıktıları ve snapshot'lar değişmedi.

## S · Sanal portföy
`FT_PROFILE=sanal`: ayrı ve işaretli veritabanı; gerçek fonlar, fiyatlar ve TÜFE; tutarla işlem girişi (fiyat yalnızca o günün kaydından, tam sayı pay); raporlar, maaş günü mesajı, alarmlar ve dengeleme gerçek kodla; `ft sanal maas-gunu-uygula` (önizleme ve onay); SANAL işaretleri; ping yok; sanal yedek ayrı ve şifreli dosya; ayrı timer şablonu (K-107…K-113).
Ön koşul: fiyat kaynağı kararı verildi (K-121, TEFAS JSON API'si, sistem istek atar); geçmiş tarihli işlemler için fiyatlar `ft sync prices --from` ile sanal veritabanına çekilir. Sanal `sync-prices` hafta içi 12:15 ve 21:45'te (K-122).
Komutlar (K-116): `ft sanal init|reset|al|sat|maas-gunu-uygula`; sunucuda `deploy/ft-sanal`; kurulum DESIGN Kurulum adım 10. Elle fiyat raporda "elle" etiketiyle (K-117); JSON'da her raporda `profile` (K-118).
Geliştirme kapısı: profil ayrımı testleri yeşil (sanal işlem gerçek veritabanına giremez, gerçek profil sanal veritabanını açmaz); tutarla işlem testleri (fiyat günü, yuvarlama, fiyat yoksa red); maaş günü uygulaması testleri (önizleme yazmaz, fiyatsız fon atlanır, ikinci uygulama reddedilir); sanal profilde ping çağrılmıyor; sanal yedek ayrı dosyada ve gerçek yedeğin budamasından etkilenmiyor.

## W1 · Web arayüzü, salt okuma
`finans.web` (Starlette, Jinja2, uvicorn), Unix soketi ve `tailscale serve`, kimlik başlığı denetimi, sayfalar (özet, varlıklar, dağılım, getiri, raporlar, alarmlar, işlemler, sistem), `finans-web.service` (K-101…K-104, K-106). Sanal portföyle geliştirilir; testlerde hayali fixture'lar kullanılır. Fiyatlar açıklandığı günle ve bayatlık uyarısıyla gösterilir (K-120). "Fiyatları güncelle" düğmesi bir istek dosyası bırakır, fiyatı `.path` birimiyle başlayan iş çeker; en az 1 saat aralık, günde en fazla 6 kez; bunun için CSRF'nin bir kısmı W1'e çekilir (K-122).
Ön koşul: cihaza Tailscale üzerinden yapılan bütün erişimlerin listesi kullanıcı onayından geçer; Pi etiketlenir ve politika her mevcut erişime açık izin verir (K-102).
Cihaz testi (DESIGN, Kurulum adım 11): HTTPS'ten önce tailnet adı rastgele ve cihaz adı nötr; telefon tailnet'te etiketsiz, anahtar süresi açık; soket ve dizini yalnız `finans`'ın; düğme `.path` birimiyle işi başlatır ve iş veritabanına yazarken bütün sayfalar Mac'ten ve telefondan açılır (WAL, `-shm`; K-123).
Geliştirme kapısı: kimlik, güvenlik başlıkları, salt okuma, CSRF, HTML kaçışı ve birim testleri yeşil; CI'da `systemd-analyze security` eşiği (K-124); cihazda Mac'ten ve telefondan 200, Pi'nin kendisinden 403, etiketli cihazlar politika gereği 443'e ulaşamaz, Funnel kapalı.
Not: kabul süresi başlamadan cihaza alınması önerilir; kabul süresince `/opt/finans` güncellemesi kabul edilen sistemi değiştirir.

## W2 · Web'den işlem girişi
İşlem girişi (önizleme → onay) ve iptali; CSRF; yazma için şifre kilidi (K-105).
Ön koşul: paylaşılan cihazın sertleştirmesi açık sorusu kapanmış.
Geliştirme kapısı: CSRF, CLI ile eşlik, şifre ve çift gönderim testleri yeşil.
Kabul kapısı: web'den girilen ilk gerçek işlemler aracı kurum ekstresiyle ±0,01 TL/kalem mutabık.

## M5 · OpenClaw ve güvenlik sertleştirmesi
JSON anlık görüntüleri ve rrsync ile aktarımı (yalnızca çekirdekten dışarı), ft-agent (boru hattı ve veri tazeliği için iki ayrı bayatlık sinyali), JSON Schema kontratı, SKILL.md, PPK özeti akışı (oranlar kodla çıkarılır), asistan botu; iki makine, ayrı OS kullanıcıları, systemd sertleştirmesinin geri kalanı (LoadCredential K-92 ve beş ayar K-98 ile M4'te geldi), makine bazında egress allowlist.
Geliştirme kapısı: Güvenlik kontrol listesi tamam; OpenClaw makinesinde veritabanı ve çekirdek sırrı yok; ajanın yazma denemesi reddediliyor.

## M6 · İleri (ihtiyaç doğarsa)
Reel XIRR geçmişi, satışlı dengeleme önerisi (FR-15), stopaj hesabı; ek işlem türleri (temettü, bölünme, birleşme), ek veri kaynakları ve bildirim kanalları.
