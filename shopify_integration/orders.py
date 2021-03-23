from typing import TYPE_CHECKING

import frappe
from frappe.utils import flt, nowdate

from shopify_integration.shopify_integration.doctype.shopify_log.shopify_log import make_shopify_log
from shopify_integration.utils import get_shopify_document, get_tax_account_head

if TYPE_CHECKING:
	from erpnext.selling.doctype.sales_order.sales_order import SalesOrder
	from shopify import Order


def create_shopify_documents(order: "Order", log_id: str = str()):
	"""
	Create the following from a Shopify order:

		- Sales Order
		- Sales Invoice (if paid)
		- Delivery Note (if fulfilled)

	Args:

		order (Order): The Shopify order data.
		log_id (str, optional): The ID of an existing Shopify Log. Defaults
			to an empty string.
	"""

	from shopify_integration.fulfilments import create_shopify_delivery
	from shopify_integration.invoices import create_shopify_invoice

	frappe.set_user("Administrator")
	frappe.flags.log_id = log_id
	sales_order = create_shopify_order(order, log_id)
	if sales_order:
		create_shopify_invoice(order, sales_order, log_id)
		create_shopify_delivery(order, sales_order, log_id)


def create_shopify_order(shopify_order: "Order", log_id: str = str()):
	"""
	Create a Sales Order document for a Shopify order.

	Args:
		shopify_order (Order): The Shopify order data.
		log_id (str, optional): The ID of an existing Shopify Log. Defaults
			to an empty string.

	Returns:
		SalesOrder: The created Sales Order document, if any, otherwise None.
	"""

	from shopify_integration.customers import validate_customer
	from shopify_integration.products import validate_item

	frappe.flags.log_id = log_id

	existing_so = get_shopify_document(doctype="Sales Order", order=shopify_order)
	if existing_so:
		existing_so: "SalesOrder"
		make_shopify_log(status="Skipped", response_data=shopify_order)
		return existing_so

	try:
		validate_customer(shopify_order)
		validate_item(shopify_order)
		sales_order = create_sales_order(shopify_order)
	except Exception as e:
		make_shopify_log(status="Error", response_data=shopify_order, exception=e)
	else:
		make_shopify_log(status="Success", response_data=shopify_order)
		return sales_order


def create_sales_order(shopify_order: "Order"):
	"""
	Helper function to create a Sales Order document for a Shopify order.

	Args:
		shopify_order (Order): The Shopify order data.

	Returns:
		SalesOrder: The created Sales Order document, if any, otherwise None.
	"""

	shopify_settings = frappe.get_single("Shopify Settings")
	customer = frappe.db.get_value("Customer", {"shopify_customer_id": shopify_order.get("customer", {}).get("id")}, "name")

	sales_order: "SalesOrder" = frappe.get_doc({
		"doctype": "Sales Order",
		"naming_series": shopify_settings.sales_order_series or "SO-Shopify-",
		"shopify_order_id": shopify_order.get("id"),
		"shopify_order_number": shopify_order.get("name"),
		"customer": customer or shopify_settings.default_customer,
		"delivery_date": nowdate(),
		"company": shopify_settings.company,
		"selling_price_list": shopify_settings.price_list,
		"ignore_pricing_rule": 1,
		"items": get_order_items(shopify_order.get("line_items"), shopify_settings),
		"taxes": get_order_taxes(shopify_order, shopify_settings),
		"apply_discount_on": "Grand Total",
		"discount_amount": flt(shopify_order.get("total_discounts")),
	})

	sales_order.flags.ignore_mandatory = True
	sales_order.save(ignore_permissions=True)
	sales_order.submit()
	frappe.db.commit()
	return sales_order


def get_order_items(order_items, shopify_settings):
	from shopify_integration.products import get_item_code

	items = []
	for shopify_item in order_items:
		item_code = get_item_code(shopify_item)
		items.append({
			"item_code": item_code,
			"item_name": shopify_item.get("name"),
			"rate": shopify_item.get("price"),
			"delivery_date": nowdate(),
			"qty": shopify_item.get("quantity"),
			"stock_uom": shopify_item.get("uom") or "Nos",
			"warehouse": shopify_settings.warehouse
		})
	return items


def get_order_taxes(shopify_order, shopify_settings):
	taxes = []

	# add shipping charges
	for shipping in shopify_order.get("shipping_lines"):
		if shipping.get("price"):
			taxes.append({
				"charge_type": "Actual",
				"account_head": get_tax_account_head("shipping"),
				"description": shipping.get("title"),
				"tax_amount": shipping.get("price"),
				"cost_center": shopify_settings.cost_center
			})

	# add additional taxes and fees
	for tax in shopify_order.get("tax_lines"):
		taxes.append({
			"charge_type": "Actual",
			"account_head": get_tax_account_head("tax"),
			"description": "{0} - {1}%".format(tax.get("title"), tax.get("rate") * 100.0),
			"tax_amount": tax.get("price"),
			"cost_center": shopify_settings.cost_center,
			"included_in_print_rate": 1 if shopify_order.get("taxes_included") else 0,
		})

	return taxes


def cancel_shopify_order(order: "Order", log_id: str = str()):
	"""
	Cancel all sales documents if a Shopify order is cancelled.

	Args:
		order (Order): The Shopify order data.
		log_id (str, optional): The ID of an existing Shopify Log.
			Defaults to an empty string.
	"""

	frappe.set_user("Administrator")
	frappe.flags.log_id = log_id

	doctypes = ["Delivery Note", "Sales Invoice", "Sales Order"]
	for doctype in doctypes:
		doc = get_shopify_document(doctype=doctype, order=order)
		if not doc:
			continue

		# recursively cancel all Shopify documents
		if doc.docstatus == 1:
			try:
				# ignore document links to Shopify Payout while cancelling
				doc.flags.ignore_links = True
				doc.cancel()
			except Exception as e:
				make_shopify_log(status="Error", response_data=order,
					exception=e, rollback=True)

		# update the financial status in all linked Shopify Payouts
		payout_transactions = frappe.get_all("Shopify Payout Transaction",
			filters={
				frappe.scrub(doctype): doc.name,
				"source_order_financial_status": ["!=", order.get("financial_status")]
			})

		for transaction in payout_transactions:
			frappe.db.set_value("Shopify Payout Transaction", transaction.name,
				"source_order_financial_status", frappe.unscrub(order.get("financial_status")))
