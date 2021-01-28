import frappe
from frappe import _


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
	if root_type == "Expense":
		return debit_field if amount < 0 else credit_field
	if root_type == "Income":
		return debit_field if amount > 0 else credit_field
	if root_type in ("Equity", "Liability"):
		if account_type in ("Receivable", "Payable"):
			return debit_field if amount > 0 else credit_field
		return debit_field if amount < 0 else credit_field


def get_tax_account_head(tax_type):
	tax_map = {
		"payout": "cash_bank_account",
		"refund": "cash_bank_account",
		"tax": "tax_account",
		"shipping": "shipping_account",
		"fee": "payment_fee_account",
		"adjustment": "payment_fee_account"
	}

	tax_field = tax_map.get(tax_type)
	if not tax_field:
		frappe.throw(_("Account not specified for '{0}'".format(frappe.unscrub(tax_type))))

	tax_account = frappe.db.get_single_value("Shopify Settings", tax_field)
	if not tax_account:
		frappe.throw(_("Account not specified for '{0}'".format(frappe.unscrub(tax_field))))

	return tax_account


def get_shopify_document(doctype, shopify_order_id):
	"""
	Get a valid linked document for a Shopify order ID.

	Args:
		doctype (str): The doctype to retrieve
		shopify_order_id (str): The Shopify order ID

	Returns:
		Document: The document for the Shopify order. Defaults to an
			empty object if no document is found.
	"""

	name = frappe.db.get_value(doctype,
		{"docstatus": ["<", 2], "shopify_order_id": shopify_order_id}, "name")
	if name:
		return frappe.get_doc(doctype, name)
	return frappe._dict()
