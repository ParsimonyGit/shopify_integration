from typing import TYPE_CHECKING, Optional

import frappe
from frappe import _
from frappe.utils import cstr

if TYPE_CHECKING:
	from shopify import Order


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


def get_tax_account_head(shop_name: str, tax_type: str):
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
		tax_type_label = frappe.unscrub(tax_type)
		frappe.throw(_(f"Account not specified for '{tax_type_label}'"))

	tax_account = frappe.db.get_value("Shopify Settings", shop_name, tax_field)
	if not tax_account:
		tax_account_label = frappe.unscrub(tax_field)
		frappe.throw(_(f"Account not specified for '{tax_account_label}'"))

	return tax_account


def get_shopify_document(
	shop_name: str,
	doctype: str,
	order: Optional["Order"] = None,
	order_id: Optional[str] = None
):
	"""
	Check if a Shopify order exists, including references from other apps.

	Args:
		shop_name (str): The name of the Shopify configuration for the store.
		doctype (str): The doctype records to check against.
		order (Order, optional): The Shopify order data.
		order_id (str, optional): The Shopify order ID.

	Returns:
		list(BaseDocument) | BaseDocument: The document object if a Shipstation
			order exists for the Shopify order, otherwise an empty list. If
			Delivery Notes need to be checked, then all found delivery documents
			are returned.
	"""

	shopify_docs = [] if doctype == "Delivery Note" else frappe._dict()

	shopify_order_id = cstr(order.id) if order else order_id
	if not shopify_order_id:
		return shopify_docs

	existing_docs = frappe.db.get_all(doctype,
		filters={
			"docstatus": ["<", 2],
			"shopify_settings": shop_name,
			"shopify_order_id": shopify_order_id,
		})

	if existing_docs:
		# multiple deliveries can be made against a single order
		if doctype == "Delivery Note":
			shopify_docs = [frappe.get_doc(doctype, doc.name) for doc in existing_docs]
		shopify_docs = frappe.get_doc(doctype, existing_docs[0].name)

	return shopify_docs
