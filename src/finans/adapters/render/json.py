from pydantic import TypeAdapter

from finans.contracts.report import AlertNotice, PaydayPlan, Report

_NOTICES = TypeAdapter(list[AlertNotice])


class JsonRenderer:
    """Kontratın kendisi; Decimal alanlar metin olarak yazılır (K-32)."""

    def report(self, report: Report) -> str:
        return report.model_dump_json(indent=2)

    def payday(self, plan: PaydayPlan) -> str:
        return plan.model_dump_json(indent=2)

    def alerts(self, notices: list[AlertNotice]) -> str:
        return _NOTICES.dump_json(notices, indent=2).decode()
