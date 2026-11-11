#!/usr/bin/env python3
"""Reproduce an illustrative lease cash-flow model, not a market-rate forecast.

Nominal USD, monthly end-of-period cash flows, pre-tax. Acquisition price,
resale, costs and capital returns are explicitly assumed. The asset model
and the financing overlay are separate, so borrowing is not counted twice.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent


def monthly_effective(annual_effective):
    if annual_effective <= -1:
        raise ValueError("effective annual rate must exceed -100 percent")
    return math.expm1(math.log1p(annual_effective) / 12)


def annuity(months, rate):
    if not isinstance(months, int) or months <= 0:
        raise ValueError("months must be a positive integer")
    if abs(rate) < 1e-14:
        return float(months)
    return -math.expm1(-months * math.log1p(rate)) / rate


def fixed_rent(inputs):
    p = inputs
    i = monthly_effective(p["asset_return_annual_effective"])
    a = annuity(p["lease_months"], i)
    residual_net = p["resale_usd"] - p["sale_cost_usd"]
    residual_pv = residual_net / (1 + i) ** p["lease_months"]
    lease = p["owner_cost_usd_month"] + (p["purchase_usd"] + p["upfront_cost_usd"] - residual_pv) / a
    # Monthly operating costs remain at month end in both timing comparisons.
    advance_lease = lease / (1 + i)
    return {"monthly_discount_rate": i, "annuity_factor": a,
            "residual_net_usd": residual_net, "residual_pv_usd": residual_pv,
            "rent_usd_month_end": lease, "rent_usd_month_advance": advance_lease,
            "gross_monthly_rent_purchase_ratio": lease / p["purchase_usd"],
            "gross_annual_rent_purchase_ratio": 12 * lease / p["purchase_usd"]}


def npv_monthly(cashflows, rate):
    return math.fsum(cf / (1 + rate) ** t for t, cf in enumerate(cashflows))


def irr_monthly(cashflows):
    """Bisection for the conventional cash flows used by this example."""
    if cashflows[0] >= 0 or any(v < 0 for v in cashflows[1:]):
        raise ValueError("this IRR helper requires one initial outflow then nonnegative receipts")
    lo, hi = -0.5, 1.0
    if npv_monthly(cashflows, lo) * npv_monthly(cashflows, hi) > 0:
        raise ValueError("IRR is outside the example's search bracket")
    for _ in range(100):
        mid = (lo + hi) / 2
        if npv_monthly(cashflows, mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def financing_overlay(inputs, rent):
    p = inputs
    opening = p["purchase_usd"] * p["debt_fraction_of_purchase"]
    j = monthly_effective(p["debt_interest_annual_effective"])
    payment = opening / annuity(p["debt_amortization_months"], j)
    balance = opening
    rows = []
    cashflows = [-(p["purchase_usd"] + p["upfront_cost_usd"] - opening)]
    for month in range(1, p["lease_months"] + 1):
        interest = balance * j
        principal = min(balance, payment - interest)
        debt_payment = interest + principal
        balance -= principal
        cash = rent - p["owner_cost_usd_month"] - debt_payment
        row = {"month": month, "rent_usd": rent, "owner_cost_usd": p["owner_cost_usd_month"],
               "interest_usd": interest, "principal_usd": principal,
               "debt_service_usd": debt_payment, "remaining_debt_usd": balance,
               "equity_operating_cash_usd": cash}
        rows.append(row)
        cashflows.append(cash)
    terminal_net = p["resale_usd"] - p["sale_cost_usd"] - balance
    cashflows[-1] += terminal_net
    im = irr_monthly(cashflows)
    y1 = rows[:12]
    # In this example the acquisition costs are capitalized into the book basis.
    accounting_basis = p["purchase_usd"] + p["upfront_cost_usd"]
    depreciation = (accounting_basis - p["accounting_residual_usd"]) / p["accounting_useful_life_years"]
    interest_y1 = math.fsum(r["interest_usd"] for r in y1)
    principal_y1 = math.fsum(r["principal_usd"] for r in y1)
    operating_cash_y1 = math.fsum(r["equity_operating_cash_usd"] for r in y1)
    accounting_profit_y1 = 12 * rent - 12 * p["owner_cost_usd_month"] - interest_y1 - depreciation
    return {"opening_debt_usd": opening,
            "initial_equity_usd": -cashflows[0],
            "debt_monthly_effective_rate": j,
            "scheduled_debt_payment_usd_month": payment,
            "remaining_debt_at_sale_usd": balance,
            "net_sale_cash_to_equity_usd": terminal_net,
            "regular_equity_cash_usd_month": rows[0]["equity_operating_cash_usd"],
            "equity_irr_annual_effective_pre_tax": (1 + im) ** 12 - 1,
            "accounting_asset_initial_basis_usd": accounting_basis,
            "first_year": {"lease_revenue_usd": 12 * rent, "owner_cost_usd": 12 * p["owner_cost_usd_month"],
                           "interest_usd": interest_y1, "principal_repaid_usd": principal_y1,
                           "depreciation_usd": depreciation,
                           "accounting_profit_usd_before_tax_and_other_items": accounting_profit_y1,
                           "equity_cash_usd_before_tax_and_terminal_sale": operating_cash_y1},
            "monthly_schedule": rows,
            "equity_cashflows_usd": cashflows}


def build():
    inputs = {"purchase_usd": 50_000_000, "upfront_cost_usd": 500_000,
              "lease_months": 120, "resale_usd": 25_000_000, "sale_cost_usd": 500_000,
              "owner_cost_usd_month": 10_000, "asset_return_annual_effective": 0.08,
              "debt_fraction_of_purchase": 0.70, "debt_interest_annual_effective": 0.06,
              "debt_amortization_months": 180, "debt_maturity_months": 120,
              "accounting_residual_usd": 7_500_000, "accounting_useful_life_years": 25}
    base = fixed_rent(inputs)
    assert inputs["debt_maturity_months"] == inputs["lease_months"]
    assert inputs["debt_amortization_months"] >= inputs["debt_maturity_months"]
    cf = [-(inputs["purchase_usd"] + inputs["upfront_cost_usd"])]
    cf += [base["rent_usd_month_end"] - inputs["owner_cost_usd_month"]] * inputs["lease_months"]
    cf[-1] += base["residual_net_usd"]
    sensitivity = []
    for key, values in [("purchase_usd", [40_000_000, 50_000_000, 60_000_000]),
                        ("asset_return_annual_effective", [0.05, 0.08, 0.11]),
                        ("resale_usd", [15_000_000, 25_000_000, 35_000_000]),
                        ("lease_months", [96, 120, 144])]:
        for value in values:
            pp = {**inputs, key: value}
            sensitivity.append({"changed_input": key, "value": value,
                                "held_fixed": "all other base inputs, including absolute resale value",
                                **fixed_rent(pp)})
    stress = []
    for resale in (15_000_000, 25_000_000, 35_000_000):
        flows = list(cf)
        flows[-1] += resale - inputs["resale_usd"]
        stress.append({"realized_resale_usd": resale, "contract_rent_usd_month": base["rent_usd_month_end"],
                       "realized_asset_irr_annual_effective": (1 + irr_monthly(flows)) ** 12 - 1,
                       "asset_npv_at_target_usd": npv_monthly(flows, base["monthly_discount_rate"])})
    return {"meta": {"as_of": "2026-11-11", "status": "illustrative_assumptions_not_market_observations",
                      "currency": "USD nominal", "timing": "monthly arrears; separate advance comparison",
                      "tax_basis": "pre-tax", "source_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
            "inputs": inputs, "base": base,
            "asset_npv_at_target_usd": npv_monthly(cf, base["monthly_discount_rate"]),
            "asset_cashflows_usd": cf, "financing": financing_overlay(inputs, base["rent_usd_month_end"]),
            "sensitivity": sensitivity, "realized_residual_stress": stress,
            "scope": ["Every numerical input is an analyst assumption, not a disclosed aircraft purchase or financing quote.",
                      "Asset required return is not the debt coupon. The financing overlay is evaluated separately.",
                      "The bank loan amortizes over 180 months but matures at month 120; its unpaid balance is repaid from sale proceeds.",
                      "Accounting residual at economic end-of-life and assumed resale at lease end are different values.",
                      "Upfront acquisition costs are capitalized into the assumed accounting asset basis; first-year cash excludes the separate time-zero purchase and financing.",
                      "No tax, insurance recovery, credit default, off-lease downtime, inflation or rent step-up is simulated.",
                      "Security deposits and maintenance-reserve reimbursements are excluded, not assumed to be free lessor profit.",
                      "Ordinary lessee-paid maintenance is not included in owner operating costs.",
                      "No production calculator coefficient is fitted to these assumed inputs."]}


if __name__ == "__main__":
    out = HERE / "out/lease_economics.json"
    out.write_text(json.dumps(build(), ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(out.relative_to(HERE.parent.parent))
