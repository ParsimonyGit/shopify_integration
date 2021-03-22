import frappe
from frappe import _
from frappe.utils import cstr


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


def get_shopify_document(doctype: str, order: dict = None, order_id: str = str()):
	"""
	Check if a Shopify order exists, including references from other apps.

	Args:
		doctype (str): The doctype records to check against.
		order (dict, optional): The Shopify order data.
		order_id (str, optional): The Shopify order ID.

	Returns:
		(BaseDocument, False): The document object, if it exists, otherwise False.
	"""

	if order:
		shopify_order_id = cstr(order.get("id"))
		shopify_order_number = cstr(order.get("name"))
	elif order_id:
		shopify_order_id = order_id
		shopify_order_number = None

	# multiple deliveries can be made against a single order
	if doctype != "Delivery Note":
		existing_doc = frappe.db.get_value(doctype,
			{"docstatus": ["<", 2], "shopify_order_id": shopify_order_id}, "name")
		if existing_doc:
			return frappe.get_doc(doctype, existing_doc)

	# if multiple integrations are active and linked to each other, such as
	# Shipstation and Shopify, use the Shopify order number to determine if
	# an order already exists from the other integration
	if shopify_order_number:
		validate_hook = frappe.get_hooks("validate_existing_shopify_document")
		if validate_hook:
			existing_docs = frappe.get_attr(validate_hook[0])(doctype, shopify_order_number)
			if existing_docs:
				return existing_docs

	return False
