from finans.contracts.report import PaydayPlan, Report


class JsonRenderer:
    """Kontratın kendisi; Decimal alanlar metin olarak yazılır (K-32)."""

    def report(self, report: Report) -> str:
        return report.model_dump_json(indent=2)

    def payday(self, plan: PaydayPlan) -> str:
        return plan.model_dump_json(indent=2)
