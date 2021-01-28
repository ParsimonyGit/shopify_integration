import frappe


def get_accounting_entry(
	account,
	amount,
	reference_type=None,
	reference_name=None,
	party_type=None,
	party_name=None,
	remark=None
):
	accounting_entry = frappe._dict({
		"account": account,
		"reference_type": reference_type,
		"reference_name": reference_name,
		"party_type": party_type,
		"party": party_name,
		"user_remark": remark
	})

	accounting_entry[get_debit_or_credit(amount, account)] = abs(amount)
	return accounting_entry


def get_debit_or_credit(amount, account):
	root_type, account_type = frappe.get_cached_value(
		"Account", account, ["root_type", "account_type"]
	)

	debit_field = "debit_in_account_currency"
	credit_field = "credit_in_account_currency"

	if root_type == "Asset":
		if account_type in ("Receivable", "Payable"):
			return debit_field if amount < 0 else credit_field
		return debit_field if amount > 0 else credit_field
	elif root_type == "Expense":
		return debit_field if amount < 0 else credit_field
	elif root_type == "Income":
		return debit_field if amount > 0 else credit_field
	elif root_type in ("Equity", "Liability"):
		if account_type in ("Receivable", "Payable"):
			return debit_field if amount > 0 else credit_field
		else:
			return debit_field if amount < 0 else credit_field
