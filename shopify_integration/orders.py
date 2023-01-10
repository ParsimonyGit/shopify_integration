from typing import TYPE_CHECKING, List

import frappe
from frappe.utils import flt, getdate, nowdate

from shopify_integration.shopify_integration.doctype.shopify_log.shopify_log import make_shopify_log
from shopify_integration.utils import get_shopify_document, get_tax_account_head

if TYPE_CHECKING:
	from erpnext.selling.doctype.sales_order.sales_order import SalesOrder
	from shopify import LineItem, Order
	from shopify_integration.shopify_integration.doctype.shopify_settings.shopify_settings import ShopifySettings


def create_shopify_documents(shop_name: str, order: "Order", log_id: str = str()):
	"""
	Create the following from a Shopify order:

		- Sales Order
		- Sales Invoice (if paid)
		- Delivery Note (if fulfilled)

	Args:

		shop_name (str): The name of the Shopify configuration for the store.
		order (Order): The Shopify order data.
		log_id (str, optional): The ID of an existing Shopify Log. Defaults
			to an empty string.
	"""

	from shopify_integration.fulfilments import create_shopify_delivery
	from shopify_integration.invoices import create_shopify_invoice

	frappe.set_user("Administrator")
	frappe.flags.log_id = log_id
	sales_order = create_shopify_order(shop_name, order, log_id)
	if sales_order:
		create_shopify_invoice(shop_name, order, sales_order, log_id)
		create_shopify_delivery(shop_name, order, sales_order, log_id)


def create_shopify_order(shop_name: str, shopify_order: "Order", log_id: str = str()):
	"""
	Create a Sales Order document for a Shopify order.

	Args:
		shop_name (str): The name of the Shopify configuration for the store.
		shopify_order (Order): The Shopify order data.
		log_id (str, optional): The ID of an existing Shopify Log. Defaults
			to an empty string.

	Returns:
		SalesOrder: The created Sales Order document, if any, otherwise None.
	"""

	from shopify_integration.customers import validate_customer
	from shopify_integration.products import validate_items

	frappe.flags.log_id = log_id

	existing_so = get_shopify_document(shop_name=shop_name, doctype="Sales Order", order=shopify_order)
	if existing_so:
		existing_so: "SalesOrder"
		make_shopify_log(shop_name, status="Skipped", response_data=shopify_order.to_dict())
		return existing_so

	try:
		validate_customer(shop_name, shopify_order)
		validate_items(shop_name, shopify_order)
		sales_order = create_sales_order(shop_name, shopify_order)
	except Exception as e:
		make_shopify_log(shop_name, status="Error", response_data=shopify_order.to_dict(), exception=e)
	else:
		make_shopify_log(shop_name, status="Success", response_data=shopify_order.to_dict())
		return sales_order


def create_sales_order(shop_name: str, shopify_order: "Order"):
	"""
	Helper function to create a Sales Order document for a Shopify order.

	Args:
		shop_name (str): The name of the Shopify configuration for the store.
		shopify_order (Order): The Shopify order data.

	Returns:
		SalesOrder: The created Sales Order document, if any, otherwise None.
	"""

	shopify_settings: "ShopifySettings" = frappe.get_doc("Shopify Settings", shop_name)
	shopify_customer = shopify_order.attributes.get("customer", frappe._dict())
	customer = frappe.db.get_value("Customer", {"shopify_customer_id": shopify_customer.id}, "name")

	sales_order: "SalesOrder" = frappe.get_doc({
		"doctype": "Sales Order",
		"naming_series": shopify_settings.sales_order_series or "SO-Shopify-",
		"shopify_settings": shopify_settings.name,
		"shopify_order_id": shopify_order.id,
		"shopify_order_number": shopify_order.attributes.get("order_number"),
		"customer": customer or shopify_settings.default_customer,
		"transaction_date": getdate(shopify_order.attributes.get("created_at")),
		"delivery_date": getdate(shopify_order.attributes.get("created_at")),
		"company": shopify_settings.company,
		"selling_price_list": shopify_settings.price_list,
		"ignore_pricing_rule": 1,
		"items": get_order_items(shopify_order.attributes.get("line_items", []), shopify_settings),
		"taxes": get_order_taxes(shopify_order, shopify_settings),
		"apply_discount_on": "Grand Total",
		"discount_amount": flt(shopify_order.attributes.get("total_discounts")),
	})

	sales_order.flags.ignore_mandatory = True
	sales_order.save(ignore_permissions=True)
	sales_order.submit()
	frappe.db.commit()
	return sales_order


def get_order_items(
	shopify_order_items: List["LineItem"], shopify_settings: "ShopifySettings"
):
	from shopify_integration.products import get_item_code

	items = []
	for shopify_item in shopify_order_items:
		item_code = get_item_code(shopify_item)
		item_group = (
			frappe.db.get_value("Item", item_code, "item_group")
			or shopify_settings.item_group
		)

		items.append({
			"item_code": item_code,
			"item_name": shopify_item.attributes.get("name"),
			"item_group": item_group,
			"rate": shopify_item.attributes.get("price"),
			"delivery_date": nowdate(),
			"qty": shopify_item.attributes.get("quantity"),
			"stock_uom": shopify_item.attributes.get("uom")
			or frappe.db.get_single_value("Stock Settings", "stock_uom"),
			"conversion_factor": 1,
			"warehouse": shopify_settings.warehouse,
		})
	return items


def get_order_taxes(shopify_order: "Order", shopify_settings: "ShopifySettings"):
	taxes = []

	# add shipping charges
	for shipping in shopify_order.attributes.get("shipping_lines"):
		if shipping.attributes.get("price"):
			taxes.append({
				"charge_type": "Actual",
				"account_head": get_tax_account_head(shopify_settings.name, "shipping"),
				"description": shipping.attributes.get("title"),
				"tax_amount": shipping.attributes.get("price"),
				"cost_center": shopify_settings.cost_center
			})

	# add additional taxes and fees
	for tax in shopify_order.attributes.get("tax_lines"):
		tax_description = "{0} - {1}%".format(
			tax.attributes.get("title"),
			tax.attributes.get("rate") * 100.0
		)

		taxes.append({
			"charge_type": "Actual",
			"account_head": get_tax_account_head(shopify_settings.name, "tax"),
			"description": tax_description,
			"tax_amount": tax.attributes.get("price"),
			"cost_center": shopify_settings.cost_center,
			"included_in_print_rate": shopify_order.attributes.get("taxes_included")
		})

	return taxes


def cancel_shopify_order(shop_name: str, order: "Order", log_id: str = str()):
	"""
	Cancel all sales documents if a Shopify order is cancelled.

	Args:
		shop_name (str): The name of the Shopify configuration for the store.
		order (Order): The Shopify order data.
		log_id (str, optional): The ID of an existing Shopify Log.
			Defaults to an empty string.
	"""

	frappe.set_user("Administrator")
	frappe.flags.log_id = log_id

	doctypes = ["Delivery Note", "Sales Invoice", "Sales Order"]
	for doctype in doctypes:
		doc = get_shopify_document(shop_name=shop_name, doctype=doctype, order=order)
		if not doc:
			continue

		# recursively cancel all Shopify documents
		if doc.docstatus == 1:
			try:
				# ignore document links to Shopify Payout while cancelling
				doc.flags.ignore_links = True
				doc.cancel()
			except Exception as e:
				make_shopify_log(shop_name, status="Error", response_data=order.to_dict(),
					exception=e, rollback=True)

		# update the financial status in all linked Shopify Payouts
		payout_transactions = frappe.get_all("Shopify Payout Transaction",
			filters={
				frappe.scrub(doctype): doc.name,
				"source_order_financial_status": ["!=", order.attributes.get("financial_status")]
			})

		for transaction in payout_transactions:
			frappe.db.set_value("Shopify Payout Transaction", transaction.name,
				"source_order_financial_status", frappe.unscrub(order.attributes.get("financial_status")))
