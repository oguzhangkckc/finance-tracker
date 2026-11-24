from finans.ports.unit_of_work import UnitOfWork


def unknown_code_message(uow: UnitOfWork, code: str) -> str:
    """Yanlış yazılmış kod tanımlı kodlarla birlikte gösterilir; düzeltmesi kolay olsun."""
    codes = sorted(item.instrument.code for item in uow.instruments.list())
    known = f" Tanımlı kodlar: {', '.join(codes)}." if codes else " Hiç varlık tanımlı değil."
    return (
        f"{code} tanımlı değil.{known} "
        "Yeni bir varlık için portfolio.toml'a ekleyip `ft config apply` çalıştır."
    )
