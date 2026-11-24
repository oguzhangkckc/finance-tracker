from typing import Protocol

from finans.contracts.report import PaydayPlan, Report


class ReportRenderer(Protocol):
    def report(self, report: Report) -> str: ...

    def payday(self, plan: PaydayPlan) -> str: ...
