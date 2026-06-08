"""Billing module facade (task-010, ADR-004).

Public surface used by other modules (watchlist enforcement, API router):
- plan limits + enforcement: `assert_within_limit`, `Plan`, `Resource`,
  `PlanLimitExceeded`, `effective_plan`;
- invoice/IPN entry points: `create_invoice`, `process_ipn`.
"""

from billing.limits import PlanLimitExceeded, assert_within_limit, effective_plan
from billing.plans import BillingPeriod, Plan, Resource
from billing.service import create_invoice
from billing.webhook import IpnResult, process_ipn

__all__ = [
    "BillingPeriod",
    "IpnResult",
    "Plan",
    "PlanLimitExceeded",
    "Resource",
    "assert_within_limit",
    "create_invoice",
    "effective_plan",
    "process_ipn",
]
