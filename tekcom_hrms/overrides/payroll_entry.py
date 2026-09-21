import frappe
from frappe import _
from frappe.utils import comma_and, flt, get_link_to_form

import erpnext
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
)


def create_do_not_include_in_total_entries(payroll_entry, submitted_salary_slips):
	"""Create one JV per (account, custom_cuenta_secundaria) pair for do_not_include_in_total components.

	Called right after the main accrual JV is created/submitted, so this is purely additive:
	Earning components debit the main account and credit the secondary account;
	Deduction components debit the secondary account and credit the main account (payable).
	"""
	if not submitted_salary_slips:
		return {"created": [], "skipped": []}

	component_accounts = {}
	groups = {}

	for salary_slip in submitted_salary_slips:
		for component_type in ("earnings", "deductions"):
			for row in salary_slip.get(component_type) or []:
				if not row.do_not_include_in_total:
					continue

				if row.salary_component not in component_accounts:
					component_accounts[row.salary_component] = frappe.db.get_value(
						"Salary Component Account",
						{"parent": row.salary_component, "company": payroll_entry.company},
						["account", "custom_cuenta_secundaria"],
						cache=True,
					) or (None, None)

				account, custom_cuenta_secundaria = component_accounts[row.salary_component]
				if not account or not custom_cuenta_secundaria:
					continue

				cost_centers = payroll_entry.get_payroll_cost_centers_for_employee(
					salary_slip.employee, salary_slip.salary_structure
				)

				bucket = groups.setdefault((account, custom_cuenta_secundaria), {})
				for cost_center, percentage in cost_centers.items():
					amount = flt(row.amount) * percentage / 100
					sub_key = (component_type, cost_center)
					bucket[sub_key] = bucket.get(sub_key, 0) + amount

	if not groups:
		return {"created": [], "skipped": []}

	accounting_dimensions = get_accounting_dimensions() or []
	company_currency = erpnext.get_company_currency(payroll_entry.company)
	precision = frappe.get_precision("Journal Entry Account", "debit_in_account_currency")
	created = []
	skipped = []

	for (account, custom_cuenta_secundaria), bucket in groups.items():
		# a pair is only ever booked once per Payroll Entry, regardless of who triggers it
		if frappe.db.exists(
			"Journal Entry Account",
			{
				"reference_type": "Payroll Entry",
				"reference_name": payroll_entry.name,
				"account": account,
				"docstatus": 1,
			},
		):
			skipped.append((account, custom_cuenta_secundaria))
			continue

		je_accounts = []
		currencies = []

		for (component_type, cost_center), amount in bucket.items():
			if not amount:
				continue

			if component_type == "earnings":
				debit_account, credit_account = account, custom_cuenta_secundaria
			else:
				debit_account, credit_account = custom_cuenta_secundaria, account

			for acc, amount_field in (
				(debit_account, "debit_in_account_currency"),
				(credit_account, "credit_in_account_currency"),
			):
				exchange_rate, amt = payroll_entry.get_amount_and_exchange_rate_for_journal_entry(
					acc, amount, company_currency, currencies
				)

				je_row = {
					"account": acc,
					"exchange_rate": flt(exchange_rate),
					"cost_center": cost_center,
					amount_field: flt(amt, precision),
				}

				# only the payable-side account carries the Payroll Entry reference
				if acc == account:
					je_row.update({"reference_type": "Payroll Entry", "reference_name": payroll_entry.name})

				payroll_entry.update_accounting_dimensions(je_row, accounting_dimensions)

				if amt:
					je_accounts.append(je_row)

		if je_accounts:
			journal_entry = payroll_entry.make_journal_entry(
				je_accounts,
				currencies,
				payroll_payable_account=account,
				voucher_type="Journal Entry",
				user_remark=_("Non-total salary component entries for {0} to {1}").format(
					payroll_entry.start_date, payroll_entry.end_date
				),
				submit_journal_entry=True,
			)
			created.append(journal_entry.name)

	return {"created": created, "skipped": skipped}


@frappe.whitelist()
def run_do_not_include_in_total_entries(payroll_entry):
	"""Manually (re)create split JVs for a Payroll Entry whose salary slips are already submitted."""
	pe = frappe.get_doc("Payroll Entry", payroll_entry)
	pe.check_permission("write")

	salary_slip_names = frappe.get_all(
		"Salary Slip", {"payroll_entry": pe.name, "docstatus": 1}, pluck="name"
	)
	if not salary_slip_names:
		frappe.throw(_("No submitted Salary Slips found for this Payroll Entry."))

	submitted_salary_slips = [frappe.get_doc("Salary Slip", name) for name in salary_slip_names]
	result = create_do_not_include_in_total_entries(pe, submitted_salary_slips) or {
		"created": [],
		"skipped": [],
	}

	if not result["created"]:
		if result["skipped"]:
			return _("No new Journal Entries were needed - all account pairs are already booked.")
		return _("No Journal Entries were needed for this Payroll Entry.")

	return _("Created {0} Journal Entry(s): {1}").format(
		len(result["created"]),
		comma_and([get_link_to_form("Journal Entry", je) for je in result["created"]]),
	)
