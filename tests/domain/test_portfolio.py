from decimal import Decimal

from finans.domain.portfolio import (
    AlertThresholds,
    InstrumentEntry,
    validate_class_labels,
    validate_portfolio,
    validate_quality,
)

D = Decimal
ENTRIES = [
    InstrumentEntry("instruments[0]", "TTE", "hisse"),
    InstrumentEntry("instruments[1]", "AFT", "dusuk_risk"),
    InstrumentEntry("instruments[2]", "ALTIN_GR", "altin"),
]
THIRDS = {"hisse": D("0.3333"), "dusuk_risk": D("0.3333"), "altin": D("0.3333")}


def _messages(**overrides: object) -> list[str]:
    arguments: dict[str, object] = {
        "entries": ENTRIES,
        "targets": {"hisse": D("0.6"), "dusuk_risk": D("0.3"), "altin": D("0.1")},
        "alerts": AlertThresholds(),
        "contribution": D(1000),
    }
    arguments.update(overrides)
    return [str(issue) for issue in validate_portfolio(**arguments)]  # type: ignore[arg-type]


def test_valid_configuration_has_no_issues() -> None:
    assert _messages() == []


def test_target_sum_message_suggests_a_concrete_fix() -> None:
    assert _messages(targets=THIRDS) == [
        "targets: ağırlıkların toplamı 1 olmalı, şu an 0.9999 (eksik 0.0001). Örneğin altin "
        "değerini 0.3333 yerine 0.3334 yaparsan toplam tam 1 olur (0.3333 + 0.3333 + 0.3334)."
    ]


def test_target_sum_above_one_is_reported_as_excess() -> None:
    (message,) = _messages(targets={"hisse": D("0.7"), "dusuk_risk": D("0.3"), "altin": D("0.1")})
    assert "şu an 1.1 (fazla 0.1)" in message
    assert "altin değerini 0.1 yerine 0 yaparsan" in message


def test_class_sets_and_duplicates_are_reported_together() -> None:
    entries = [
        *ENTRIES,
        InstrumentEntry("instruments[3]", "BTC", "kripto"),
        InstrumentEntry("instruments[4]", "TTE", "hisse"),
    ]
    targets = {"hisse": D("0.5"), "dusuk_risk": D("0.3"), "altin": D("0.1"), "emtia": D("0.1")}
    assert _messages(entries=entries, targets=targets) == [
        'instruments[3].asset_class: "kripto" hedeflerde yok. '
        "Hedef sınıflar: altin, dusuk_risk, emtia, hisse.",
        'instruments[4].code: "TTE" iki kez tanımlı (ilki instruments[0]).',
        "targets.emtia: bu sınıfta tanımlı varlık yok.",
    ]


def test_negative_target_and_invalid_thresholds() -> None:
    messages = _messages(
        targets={"hisse": D("1.1"), "dusuk_risk": D("-0.1"), "altin": D(0)},
        alerts=AlertThresholds(open_above=D("0.03"), close_below=D("0.05"), reminder_days=0),
        contribution=D(-1),
    )
    assert messages == [
        "targets.dusuk_risk: negatif olamaz; -0.1 verildi.",
        "alerts: close_below (0.05), open_above (0.03) değerinden küçük olmalı.",
        "alerts.reminder_days: en az 1 olmalı; 0 verildi.",
        "contribution.monthly: negatif olamaz; -1 verildi.",
    ]


def test_no_suggestion_when_the_last_class_cannot_absorb_the_excess() -> None:
    (message,) = _messages(targets={"hisse": D("1.0"), "dusuk_risk": D("0.3"), "altin": D("0.1")})
    assert message == "targets: ağırlıkların toplamı 1 olmalı, şu an 1.4 (fazla 0.4)."


def test_thresholds_must_lie_between_zero_and_one() -> None:
    assert _messages(alerts=AlertThresholds(open_above=D("1.5"), close_below=D("0.03"))) == [
        "alerts: eşikler 0 ile 1 arasında olmalı."
    ]


def test_entries_with_unknown_fields_do_not_cause_false_class_errors() -> None:
    entries = [*ENTRIES, InstrumentEntry("instruments[3]", None, None)]
    assert _messages(entries=entries) == []


def test_sum_is_not_checked_when_a_target_value_was_invalid() -> None:
    targets = {"hisse": D("0.6"), "dusuk_risk": None, "altin": D("0.1")}
    assert _messages(targets=targets) == []


def test_empty_sections_are_reported() -> None:
    assert _messages(entries=[], targets={}) == [
        "instruments: en az bir varlık tanımlanmalı.",
        "targets: en az bir hedef sınıf tanımlanmalı.",
    ]


def test_jump_thresholds_must_lie_in_zero_one_and_unparsed_values_are_skipped() -> None:
    issues = validate_quality(
        {"hisse": Decimal("0.15"), "altin": Decimal(0), "kripto": Decimal("1.5"), "x": None}
    )
    assert [str(issue) for issue in issues] == [
        "quality.jump.altin: 0 ile 1 arasında olmalı (0.15 = %15); 0 verildi.",
        "quality.jump.kripto: 0 ile 1 arasında olmalı (0.15 = %15); 1.5 verildi.",
    ]


def test_class_labels_must_name_known_classes_and_be_short_and_not_empty() -> None:
    issues = validate_class_labels(
        {"hisse": "Türkiye hisse", "tahvil": "Tahvil", "dusuk_risk": "  ", "altin": "A" * 41},
        {"hisse", "dusuk_risk", "altin"},
    )

    assert [str(issue) for issue in issues] == [
        'sinif_adlari.tahvil: "tahvil" bilinen bir sınıf değil. '
        "Sınıflar: altin, dusuk_risk, hisse.",
        "sinif_adlari.dusuk_risk: boş olamaz.",
        "sinif_adlari.altin: en çok 40 karakter olmalı; 41 verildi.",
    ]
    assert validate_class_labels({"hisse": "Türkiye hisse"}, {"hisse"}) == []
