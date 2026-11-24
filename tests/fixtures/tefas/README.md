# TEFAS kayıtlı yanıtları

2026-11-24'te kullanıcının kendi makinesinde `scripts/record_tefas.py` ile alınan gerçek yanıtlar;
bayt bayt değiştirilmeden saklanır. Fonlar TEFAS listesinden rastgele seçildi (kullanıcının
fonları değil). İstekler `POST https://www.tefas.gov.tr/api/funds/<uç nokta>`, JSON gövde,
User-Agent `finans-takip/0.1.0 (kisisel kullanim)`.

| Dosya | Uç nokta | Gövde |
| --- | --- | --- |
| `fiyat_bco_periyod1.json` | `fonFiyatBilgiGetir` | `{"fonKodu": "BCO", "dil": "TR", "periyod": 1}` |
| `fiyat_ajh_periyod1.json` | `fonFiyatBilgiGetir` | `{"fonKodu": "AJH", "dil": "TR", "periyod": 1}` |
| `fiyat_eoz_periyod1.json` | `fonFiyatBilgiGetir` | `{"fonKodu": "EOZ", "dil": "TR", "periyod": 1}` |
| `fiyat_bco_periyod60.json` | `fonFiyatBilgiGetir` | `{"fonKodu": "BCO", "dil": "TR", "periyod": 60}` |
| `aralik_bco_28gun.json` | `fonGnlBlgSiraliGetir` | `fonTipi` YAT, `fonKodu` BCO, `basTarih` 20261027, `bitTarih` 20261123 |
| `aralik_bco_60gun_hata.json` | `fonGnlBlgSiraliGetir` | aynı, `basTarih` 20260925: "Tarih aralığı 1 ayı aşamaz" |
| `liste_byf_2026-11-23.json` | `fonGnlBlgSiraliGetir` | `fonTipi` BYF, `fonKodu` null, tek gün 20261123 |

`fonGnlBlgSiraliGetir` gövdesinin diğer alanları: `aramaMetni`, `fonTurKod`, `fonGrubu`,
`sfonTurKod`, `fonTurAciklama`, `kurucuKod`, `sira`, `yon` null; `basSira` 1, `bitSira` 9999,
`dil` "TR".

Kaynak: TEFAS (Takasbank). Sitenin robots.txt dosyası `/api/` yolunu otomatik erişime kapatıyor;
bu kayıtlar kullanıcının kararıyla alındı (DESIGN.md K-71).
