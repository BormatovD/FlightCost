#!/usr/bin/env python3
"""Independent cash-flow verification; does not import the article's model.

Uses discounted cash-flow sums and a closed-form debt balance, rather than
the producer's annuity helper and iterative amortization implementation.
"""
from pathlib import Path
import hashlib
import json
import math

HERE = Path(__file__).resolve().parent
INPUT = HERE.parent / "out/lease_economics.json"


def value_at_rate(cashflows, annual):
    return math.fsum(c / (1 + annual) ** (t / 12) for t, c in enumerate(cashflows))


def annual_irr(cashflows):
    # Newton in annual log-discount space, independently from producer bisection.
    x = math.log1p(.08)
    for _ in range(30):
        terms = [c * math.exp(-x * t / 12) for t, c in enumerate(cashflows)]
        f = math.fsum(terms)
        derivative = math.fsum(-t / 12 * term for t, term in enumerate(terms))
        change = f / derivative
        x -= change
        if abs(change) < 1e-14:
            break
    return math.expm1(x)


def rental(p):
    n = p["lease_months"]
    discount = [(1 + p["asset_return_annual_effective"]) ** (-t / 12) for t in range(n + 1)]
    operating_pv = p["owner_cost_usd_month"] * sum(discount[1:])
    sale_pv = (p["resale_usd"] - p["sale_cost_usd"]) * discount[-1]
    required_rent_pv = p["purchase_usd"] + p["upfront_cost_usd"] + operating_pv - sale_pv
    return required_rent_pv / sum(discount[1:]), required_rent_pv / sum(discount[:-1])


def main():
    d = json.loads(INPUT.read_text())
    p, b, f = d["inputs"], d["base"], d["financing"]
    checked, failures = [], []

    def check(name, actual, expected, tolerance=1e-5):
        error = abs(actual - expected)
        checked.append({"name": name, "independent_value": actual, "stored_value": expected,
                        "absolute_difference": error, "tolerance": tolerance})
        if error > tolerance:
            failures.append(name)

    arrears, advance = rental(p)
    check("monthly_rent_arrears", arrears, b["rent_usd_month_end"])
    check("monthly_rent_advance_operating_costs_still_arrears", advance, b["rent_usd_month_advance"])
    n = p["lease_months"]
    i = (1 + p["debt_interest_annual_effective"]) ** (1 / 12) - 1
    principal = p["purchase_usd"] * p["debt_fraction_of_purchase"]
    payment = principal / sum((1 + i) ** -t for t in range(1, p["debt_amortization_months"] + 1))
    balances = [principal * (1 + i) ** t - payment * ((1 + i) ** t - 1) / i for t in range(n + 1)]
    check("monthly_debt_payment", payment, f["scheduled_debt_payment_usd_month"])
    check("debt_balloon_after_last_scheduled_payment", balances[-1], f["remaining_debt_at_sale_usd"])
    sale_cash = p["resale_usd"] - p["sale_cost_usd"] - balances[-1]
    check("sale_less_cost_less_balloon", sale_cash, f["net_sale_cash_to_equity_usd"])
    equity = p["purchase_usd"] + p["upfront_cost_usd"] - principal
    check("time_zero_equity", equity, f["initial_equity_usd"])
    equity_flows = [-equity] + [arrears - p["owner_cost_usd_month"] - payment] * n
    equity_flows[-1] += sale_cash
    check("equity_annual_effective_irr", annual_irr(equity_flows), f["equity_irr_annual_effective_pre_tax"], 1e-12)
    check("equity_irr_zero_npv", value_at_rate(equity_flows, annual_irr(equity_flows)), 0, 1e-5)
    check("all_equity_cashflows_max_error", max(abs(x-y) for x,y in zip(equity_flows,f["equity_cashflows_usd"])),0)
    errors = {}
    for row in f["monthly_schedule"]:
        t = row["month"]
        expected = {"remaining_debt_usd": balances[t], "interest_usd": balances[t-1] * i,
                    "principal_usd": balances[t-1] - balances[t], "debt_service_usd": payment,
                    "equity_operating_cash_usd": arrears - p["owner_cost_usd_month"] - payment}
        for k,v in expected.items():
            errors[k] = max(errors.get(k,0), abs(row[k] - v))
    for k, error in errors.items():
        check("120_month_schedule_" + k + "_max_error", error, 0)
    y = f["first_year"]
    interest_year1 = math.fsum(balances[t] * i for t in range(12))
    principal_year1 = principal - balances[12]
    depreciation = (p["purchase_usd"] + p["upfront_cost_usd"] - p["accounting_residual_usd"]) / p["accounting_useful_life_years"]
    profit = 12 * (arrears - p["owner_cost_usd_month"]) - interest_year1 - depreciation
    cash = 12 * (arrears - p["owner_cost_usd_month"] - payment)
    for name, actual in {"interest_usd": interest_year1,"principal_repaid_usd":principal_year1,
        "depreciation_usd":depreciation,"accounting_profit_usd_before_tax_and_other_items":profit,
        "equity_cash_usd_before_tax_and_terminal_sale":cash}.items():
        check("first_year_"+name,actual,y[name])
    check("cash_profit_reconciliation",profit + depreciation - principal_year1,cash)
    asset_flows = [-(p["purchase_usd"]+p["upfront_cost_usd"])] + [arrears-p["owner_cost_usd_month"]]*n
    asset_flows[-1] += p["resale_usd"]-p["sale_cost_usd"]
    check("asset_npv_target",value_at_rate(asset_flows,p["asset_return_annual_effective"]),0)
    check("asset_irr_target",annual_irr(asset_flows),p["asset_return_annual_effective"],1e-12)
    advance_flows = [-(p["purchase_usd"]+p["upfront_cost_usd"])+advance] + [advance-p["owner_cost_usd_month"]]*(n-1)
    advance_flows.append(p["resale_usd"]-p["sale_cost_usd"]-p["owner_cost_usd_month"])
    check("advance_rent_asset_npv_target",value_at_rate(advance_flows,p["asset_return_annual_effective"]),0)
    for row in d["sensitivity"]:
        changed = {**p,row["changed_input"]:row["value"]}
        r,ra = rental(changed)
        check(f"sensitivity_{row['changed_input']}_{row['value']}_arrears",r,row["rent_usd_month_end"])
        check(f"sensitivity_{row['changed_input']}_{row['value']}_advance",ra,row["rent_usd_month_advance"])
    for row in d["realized_residual_stress"]:
        flows=list(asset_flows)
        flows[-1]+=row["realized_resale_usd"]-p["resale_usd"]
        check(f"residual_{row['realized_resale_usd']}_irr",annual_irr(flows),row["realized_asset_irr_annual_effective"],1e-12)
        check(f"residual_{row['realized_resale_usd']}_npv",value_at_rate(flows,p["asset_return_annual_effective"]),row["asset_npv_at_target_usd"])
    result = {"stage":"0056","status":"pass" if not failures else "fail","independent":True,
        "input_sha256":hashlib.sha256(INPUT.read_bytes()).hexdigest(),"method":"Explicit monthly discounted cash-flow sums; closed-form debt balance; annual log-rate Newton IRR; no producer module imported.",
        "checks":checked,"failed_checks":failures,
        "scope":["All inputs are illustrative assumptions, not actual market observations or disclosed deal terms.",
                 "Gross rent/purchase ratios are not net investment returns.",
                 "Asset NPV excludes financing; equity cash flows subtract both scheduled service and residual debt exactly once.",
                 "Advance rent is solved with owner expenses still at month end.",
                 "Accounting depreciation and terminal market resale are deliberately different concepts.",
                 "Sensitivity holds absolute resale fixed when purchase price or tenor changes; it is a partial sensitivity, not a new market forecast."]}
    (HERE/"lease_economics_0056.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(result["status"],len(checked),"checks",failures)


if __name__=="__main__":
    main()
