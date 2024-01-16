from typing import TYPE_CHECKING, List

import frappe
from frappe.utils import flt, getdate, nowdate

from shopify_integration.shopify_integration.doctype.shopify_log.shopify_log import (
	make_shopify_log,
)
from shopify_integration.utils import get_shopify_document, get_tax_account_head

if TYPE_CHECKING:
	from erpnext.selling.doctype.sales_order.sales_order import SalesOrder
	from shopify import LineItem, Order

	from shopify_integration.shopify_integration.doctype.shopify_settings.shopify_settings import (
		ShopifySettings,
	)


def create_shopify_documents(
	shop_name: str, order_id: str, log_id: str = "", amended_from: str = ""
):
	"""
	Create the following from a Shopify order:

	- Sales Order
	- Sales Invoice (if paid)
	- Delivery Note (if fulfilled)

	:param shop_name: The name of the Shopify configuration for the store
	:param order_id: The Shopify order ID
	:param log_id: (optional) The ID of an existing Shopify Log
	:param amended_from: (optional) The name of the original cancelled Sales Order
	"""

	from shopify_integration.fulfilments import create_shopify_delivery
	from shopify_integration.invoices import create_shopify_invoice

	frappe.set_user("Administrator")
	frappe.flags.log_id = log_id

	order = get_shopify_order(shop_name, order_id, log_id)
	if not order:
		return

	sales_order = create_shopify_order(shop_name, order, log_id, amended_from)
	if sales_order:
		create_shopify_invoice(shop_name, order, sales_order, log_id)
		create_shopify_delivery(shop_name, order, sales_order, log_id)


def get_shopify_order(shop_name: str, order_id: str, log_id: str = ""):
	frappe.flags.log_id = log_id

	settings: "ShopifySettings" = frappe.get_doc("Shopify Settings", shop_name)
	orders = settings.get_orders(order_id)
	if not orders:
		make_shopify_log(
			shop_name,
			status="Error",
			response_data=f"Order '{order_id}' not found in Shopify",
		)
		return

	order: "Order"
	order = orders[0]
	return order


def create_shopify_order(
	shop_name: str,
	shopify_order: "Order",
	log_id: str = "",
	amended_from: str = "",
):
	"""
	Create a Sales Order document for a Shopify order.

	:param shop_name: The name of the Shopify configuration for the store
	:param order_id: The Shopify order ID
	:param log_id: (optional) The ID of an existing Shopify Log
	:param amended_from: (optional) The name of the original cancelled Sales Order
	:return: The created Sales Order document, if any, otherwise None
	"""

	from shopify_integration.customers import validate_customer
	from shopify_integration.products import validate_items

	frappe.flags.log_id = log_id

	if existing_so := get_shopify_document(
		shop_name=shop_name, doctype="Sales Order", order=shopify_order
	):
		existing_so: "SalesOrder"
		make_shopify_log(shop_name, status="Skipped", response_data=shopify_order.to_dict())
		return existing_so

	try:
		validate_customer(shop_name, shopify_order)
		validate_items(shop_name, shopify_order)
		sales_order = create_sales_order(shop_name, shopify_order, amended_from=amended_from)
	except Exception as e:
		make_shopify_log(
			shop_name,
			status="Error",
			response_data=shopify_order.to_dict(),
			exception=e,
		)
	else:
		make_shopify_log(shop_name, status="Success", response_data=shopify_order.to_dict())
		return sales_order


def update_shopify_order(shop_name: str, order_id: str, log_id: str = ""):
	"""
	Webhook endpoint to process changes in a Shopify order.

	Instead of updating the existing documents, cancel them and create a new series of
	sales documents for the Shopify order.

	:param shop_name: The name of the Shopify configuration for the store
	:param order_id: The Shopify order ID
	:param log_id: (optional) The ID of an existing Shopify Log
	"""

	if existing_so := get_shopify_document(
		shop_name=shop_name, doctype="Sales Order", order_id=order_id
	):
		cancel_shopify_order(shop_name, order_id, log_id)
		create_shopify_documents(shop_name, order_id, log_id, amended_from=existing_so.name)


def create_sales_order(shop_name: str, shopify_order: "Order", *, amended_from: str = ""):
	"""
	Helper function to create a Sales Order document for a Shopify order.

	:param shop_name: The name of the Shopify configuration for the store
	:param shopify_order: The Shopify order data
	:param amended_from: (optional) The name of the original cancelled Sales Order
	:return: The created Sales Order document, if any, otherwise None
	"""

	shopify_settings: "ShopifySettings" = frappe.get_doc("Shopify Settings", shop_name)
	shopify_customer = shopify_order.attributes.get("customer", frappe._dict())
	customer = frappe.db.get_value("Customer", {"shopify_customer_id": shopify_customer.id}, "name")

	shopify_order_name = shopify_order.attributes.get("name")
	shopify_order_name = shopify_order_name.split("#")[-1]

	sales_order: "SalesOrder" = frappe.get_doc(
		{
			"doctype": "Sales Order",
			"naming_series": shopify_settings.sales_order_series or "SO-Shopify-",
			"shopify_settings": shopify_settings.name,
			"shopify_order_id": shopify_order.id,
			"shopify_order_number": shopify_order.attributes.get("order_number"),
			"shopify_order_name": shopify_order_name,
			"customer": customer or shopify_settings.default_customer,
			"transaction_date": getdate(shopify_order.attributes.get("created_at")),
			"delivery_date": getdate(shopify_order.attributes.get("created_at")),
			"company": shopify_settings.company,
			"selling_price_list": shopify_settings.price_list,
			"ignore_pricing_rule": 1,
			"items": get_order_items(shopify_order.attributes.get("line_items", []), shopify_settings),
			"taxes": get_order_taxes(shopify_order, shopify_settings),
			"apply_discount_on": "Grand Total",
			"discount_amount": flt(shopify_order.attributes.get("current_total_discounts")),
			"amended_from": amended_from,
		}
	)

	sales_order.flags.ignore_mandatory = True
	sales_order.save(ignore_permissions=True)
	sales_order.submit()
	frappe.db.commit()
	return sales_order


def get_order_items(shopify_order_items: list["LineItem"], shopify_settings: "ShopifySettings"):
	items = []
	for shopify_item in shopify_order_items:
		items.append(get_order_item(shopify_item, shopify_settings))
	return items


def get_order_item(shopify_item: "LineItem", shopify_settings: "ShopifySettings"):
	from shopify_integration.products import get_item_code

	item_code = get_item_code(shopify_item)
	item_name = shopify_item.attributes.get("name", "")[:140]
	item_group = frappe.db.get_value("Item", item_code, "item_group") or shopify_settings.item_group

	stock_uom = shopify_item.attributes.get("uom") or frappe.db.get_single_value(
		"Stock Settings", "stock_uom"
	)

	# TODO: both quantity and fulfillable_quantity don't denote actual ordered quantity
	# figure out a way to get the actual ordered quantity (including edits)
	qty = flt(
		shopify_item.attributes.get("fulfillable_quantity") or shopify_item.attributes.get("quantity")
	)

	return {
		"shopify_order_item_id": str(shopify_item.id),
		"item_code": item_code,
		"item_name": item_name,
		"item_group": item_group,
		"rate": flt(shopify_item.attributes.get("price")),
		# TODO: if items with discounts are edited, Shopify's API doesn't have an easy
		# way to get the discount amount
		# "discount_amount": flt(shopify_item.attributes.get("total_discount")),
		"delivery_date": nowdate(),
		"qty": qty,
		"stock_uom": stock_uom,
		"conversion_factor": 1,
		"warehouse": shopify_settings.warehouse,
	}


def get_order_taxes(shopify_order: "Order", shopify_settings: "ShopifySettings"):
	taxes = []

	# add shipping charges
	shipping_descriptions = []
	for shipping in shopify_order.attributes.get("shipping_lines"):
		shipping_descriptions.append(shipping.attributes.get("title"))
		taxes.append(
			{
				"charge_type": "Actual",
				"account_head": get_tax_account_head(shopify_settings.name, "shipping"),
				"description": shipping.attributes.get("title"),
				"tax_amount": flt(shipping.attributes.get("price")),
				"cost_center": shopify_settings.cost_center,
			}
		)

	# add additional taxes and fees
	for tax in shopify_order.attributes.get("tax_lines"):
		title = tax.attributes.get("title")
		if rate := tax.attributes.get("rate"):
			tax_description = f"{title} - {rate * 100.0}%"
		else:
			tax_description = title

		taxes.append(
			{
				"charge_type": "Actual",
				"account_head": get_tax_account_head(shopify_settings.name, "tax"),
				"description": tax_description,
				"tax_amount": flt(tax.attributes.get("price")),
				"cost_center": shopify_settings.cost_center,
				"included_in_print_rate": shopify_order.attributes.get("taxes_included"),
			}
		)

	# TODO: Shopify's API doesn't have a clear way to identify changes in taxes
	# from orders being edited. Instead of calculating the difference, we'll
	# just add a tax line for the difference; since shipping lines are not
	# considered as a "tax" in Shopify. we'll remove them from the total taxes
	erpnext_order_taxes = sum(
		tax.get("tax_amount") for tax in taxes if tax.get("description") not in shipping_descriptions
	)

	# calculate the difference between the Shopify taxes with the total taxes in the
	# ERPNext sales order without the shipping lines
	shopify_order_taxes = flt(shopify_order.attributes.get("current_total_tax"))
	currency_precision = flt(frappe.db.get_single_value("System Settings", "currency_precision"))

	difference = flt(shopify_order_taxes - erpnext_order_taxes, precision=currency_precision or 2)

	if difference:
		taxes.append(
			{
				"charge_type": "Actual",
				"account_head": get_tax_account_head(shopify_settings.name, "tax"),
				"description": "Tax Difference from Order Edits",
				"tax_amount": difference,
				"cost_center": shopify_settings.cost_center,
			}
		)

	return taxes


def cancel_shopify_order(shop_name: str, order_id: str, log_id: str = ""):
	"""
	Cancel all sales documents if a Shopify order is cancelled.

	:param shop_name: The name of the Shopify configuration for the store
	:param order_id: The Shopify order ID
	:param log_id: (optional) The ID of an existing Shopify Log
	"""

	frappe.set_user("Administrator")
	frappe.flags.log_id = log_id

	order = get_shopify_order(shop_name, order_id, log_id)
	if not order:
		return

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
				make_shopify_log(
					shop_name,
					status="Error",
					response_data=order.to_dict(),
					exception=e,
					rollback=True,
				)

		# update the financial status in all linked Shopify Payouts
		payout_transactions = frappe.get_all(
			"Shopify Payout Transaction",
			filters={
				frappe.scrub(doctype): doc.name,
				"source_order_financial_status": [
					"!=",
					order.attributes.get("financial_status"),
				],
			},
		)

		for transaction in payout_transactions:
			frappe.db.set_value(
				"Shopify Payout Transaction",
				transaction.name,
				"source_order_financial_status",
				frappe.unscrub(order.attributes.get("financial_status")),
			)
