from typing import Protocol

from finans.contracts.report import AlertNotice, PaydayPlan, Report


class ReportRenderer(Protocol):
    def report(self, report: Report) -> str: ...

    def payday(self, plan: PaydayPlan) -> str: ...

    def alerts(self, notices: list[AlertNotice]) -> str: ...
