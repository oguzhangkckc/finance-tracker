"""TÜİK referanslarıyla TÜFE zincirlemesi (K-40).

Değerlerin kaynağı TÜİK'in istatistiksel tablolarıdır (Dağıtım Yönetim Sistemi):
https://databrowser2.tuik.gov.tr → İstatistiksel Faaliyetlerin Sınıflaması → Fiyat İstatistikleri
→ Tüketici Fiyat Endeksi. Seçim: TR, aylık, TÜFE genel endeks (COICOP 0), gösterge F_TFE.
- 2003=100 endeksi: veri kümesi TR,DF_TUFE_SDMX_2003 (1.0), DEGISIM=1 "Endeks".
- 2025=100 endeksi: veri kümesi TR,DF_TUFE_SDMX_TT10 (1.0), DEGISIM=1 "Endeks".
- Yıllık değişim: aynı veri kümesi, DEGISIM=4 "Bir önceki yılın aynı ayına göre değişim oranı (%)".
Erişim: 2026-11-24.

Her satırdaki bülten linki (veriportali.tuik.gov.tr/tr/press/…) elle kontrol içindir. Bülten
sayfaları otomatik istemcilere 403 döndürdüğü için değerler bültenlerden değil, yukarıdaki
tablolardan alındı. Bülten ile tablo farklı çıkarsa bülten esas alınır.
"""

from decimal import Decimal

from finans.domain.inflation import CpiSeries, annual_inflation, chain_link
from finans.domain.models import CpiPoint, YearMonth

D = Decimal
PRESS = "https://veriportali.tuik.gov.tr/tr/press/"
LINK_MONTH = YearMonth(2025, 12)
TOLERANCE_POINTS = D("0.01")

# (dönem, 2003=100 endeksi, bülten)
OLD_BASE_2003 = [
    ("2025-01", "2819.65", PRESS + "54176"),
    ("2025-02", "2883.75", PRESS + "54177"),
    ("2025-03", "2954.69", PRESS + "54178"),
    ("2025-04", "3043.23", PRESS + "54179"),
    ("2025-05", "3089.74", PRESS + "54180"),
    ("2025-06", "3132.17", PRESS + "54181"),
    ("2025-07", "3196.66", PRESS + "54182"),
    ("2025-08", "3261.72", PRESS + "54183"),
    ("2025-09", "3367.22", PRESS + "54184"),
    ("2025-10", "3453.09", PRESS + "54185"),
    ("2025-11", "3482.96", PRESS + "54186"),
    ("2025-12", "3513.87", PRESS + "58294"),
]

# (dönem, 2025=100 endeksi, yıllık değişim %, bülten). Aralık 2025'in yeni bazdaki değeri yalnızca
# tabloda var; o ayın bülteni eski bazda yayımlandı.
NEW_BASE_2025 = [
    ("2025-12", "110.386963", None, None),
    ("2026-01", "115.73", "30.65", PRESS + "58293"),
    ("2026-02", "119.16", "31.53", PRESS + "58287"),
    ("2026-03", "121.47", "30.87", PRESS + "58295"),
    ("2026-04", "126.55", "32.37", PRESS + "58288"),
    ("2026-05", "128.72", "32.61", PRESS + "58296"),
    ("2026-06", "129.99", "32.11", PRESS + "58289"),
    ("2026-07", "132.31", "31.75", PRESS + "58297"),
    ("2026-08", "134.75", "31.51", PRESS + "58290"),
    ("2026-09", "137.23", "29.73", PRESS + "58298"),
    ("2026-10", "140.77", "29.77", PRESS + "58291"),
]

# TÜİK 2025'in tamamını yeni bazda da yayımlıyor (aynı TT10 tablosu).
JANUARY_2025_IN_NEW_BASE = D("88.578291")


def _linked() -> CpiSeries:
    old = CpiSeries(CpiPoint(YearMonth.parse(p), D(v)) for p, v, _ in OLD_BASE_2003)
    new = CpiSeries(CpiPoint(YearMonth.parse(p), D(v)) for p, v, _, _ in NEW_BASE_2025)
    return chain_link(old, new, link=LINK_MONTH)


def test_chain_linked_annual_rates_match_tuik_within_a_hundredth_of_a_point() -> None:
    linked = _linked()
    deviations = {
        period: annual_inflation(linked, YearMonth.parse(period)) * 100 - D(published)
        for period, _, published, _ in NEW_BASE_2025
        if published is not None
    }
    assert len(deviations) == 10
    outside = {p: d for p, d in deviations.items() if abs(d) > TOLERANCE_POINTS}
    assert outside == {}, outside


def test_old_series_rescaled_at_december_reproduces_tuik_new_base() -> None:
    rescaled = _linked().index(YearMonth(2025, 1))
    assert abs(rescaled - JANUARY_2025_IN_NEW_BASE) < D("0.000001")
