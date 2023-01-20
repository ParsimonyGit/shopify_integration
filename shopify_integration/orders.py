import json
from typing import TYPE_CHECKING, Dict, List

import frappe
from erpnext.controllers.accounts_controller import update_child_qty_rate
from frappe.utils import flt, getdate, nowdate

from shopify_integration.shopify_integration.doctype.shopify_log.shopify_log import make_shopify_log
from shopify_integration.utils import get_shopify_document, get_tax_account_head

if TYPE_CHECKING:
	from erpnext.selling.doctype.sales_order.sales_order import SalesOrder
	from shopify import LineItem, Order
	from shopify_integration.shopify_integration.doctype.shopify_settings.shopify_settings import ShopifySettings


def create_shopify_documents(shop_name: str, order_id: str, log_id: str = str()):
	"""
	Create the following from a Shopify order:

		- Sales Order
		- Sales Invoice (if paid)
		- Delivery Note (if fulfilled)

	Args:

		shop_name (str): The name of the Shopify configuration for the store.
		order_id (str): The Shopify order ID.
		log_id (str, optional): The ID of an existing Shopify Log. Defaults
			to an empty string.
	"""

	from shopify_integration.fulfilments import create_shopify_delivery
	from shopify_integration.invoices import create_shopify_invoice

	frappe.set_user("Administrator")
	frappe.flags.log_id = log_id

	order = get_shopify_order(shop_name, order_id, log_id)
	if not order:
		return

	sales_order = create_shopify_order(shop_name, order, log_id)
	# if sales_order:
	# 	create_shopify_invoice(shop_name, order, sales_order, log_id)
	# 	create_shopify_delivery(shop_name, order, sales_order, log_id)


def get_shopify_order(shop_name: str, order_id: str, log_id: str = str()):
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


def update_shopify_order(shop_name: str, order_id: str, data: Dict, log_id: str = str()):
	"""
	Webhook endpoint to sync changes from a Shopify order with a Sales Order document.

	Args:
		shop_name (str): The name of the Shopify configuration for the store.
		order_id (str): The Shopify order ID.
		data (dict): The webhook data.
		log_id (str, optional): The ID of an existing Shopify Log. Defaults
			to an empty string.
	"""

	def update_items(existing_so: "SalesOrder"):
		changed_items = [
			item.as_dict(convert_dates_to_str=True) for item in existing_so.items
		]

		# if no new items are being added, flag the system to not create new rows
		# and just update the existing rows; if new rows are created, integration
		# details are lost
		for item in changed_items:
			item.docname = item.name

		update_child_qty_rate(
			"Sales Order", json.dumps(changed_items), existing_so.name, "items"
		)

	from shopify_integration.products import validate_items

	order = get_shopify_order(shop_name, order_id, log_id)
	if not order:
		return

	existing_so = get_shopify_document(
		shop_name=shop_name, doctype="Sales Order", order_id=order_id
	)

	if not existing_so:
		make_shopify_log(shop_name, status="Error", response_data=order.to_dict())
		return

	# if new items are added to the order, create them first
	validate_items(shop_name, order)
	shopify_order_items = order.attributes.get("line_items", [])
	line_items: Dict = data.get("line_items", {})
	shopify_settings: "ShopifySettings" = frappe.get_doc("Shopify Settings", shop_name)

	# process item or quantity additions
	line_item_additions = line_items.get("additions", [])
	for added in line_item_additions:
		existing_order_item = [
			so_item
			for so_item in existing_so.items
			if str(added.get("id")) == so_item.get("shopify_order_item_id")
		]

		if existing_order_item:
			existing_order_item = existing_order_item[0]
			existing_order_item.qty += added.get("delta")
		else:
			# if it's a new item, add it into the items table
			for shopify_order_item in shopify_order_items:
				if added.get("id") == shopify_order_item.id:
					order_item = get_order_item(shopify_order_item, shopify_settings)
					existing_so.append("items", order_item)

					# HACK: if new rows are added using `update_child_qty_rate`,
					# non-standard fields are lost; so, we need to reload the
					# document and update the custom details in the new row
					update_items(existing_so)
					existing_so.load_from_db()
					added_item = existing_so.items[-1]
					added_item.db_set("shopify_order_item_id", str(added.get("id")))
					added_item.db_set(
						"discount_amount",
						flt(shopify_order_item.attributes.get("total_discount")),
					)
					break

	total_discounts = sum(item.discount_amount for item in existing_so.items)
	existing_so.db_set("discount_amount", total_discounts)

	# process item or quantity deletions
	line_item_removals = line_items.get("removals", [])
	for removed in line_item_removals:
		existing_order_item = [
			so_item
			for so_item in existing_so.items
			if str(removed.get("id")) == so_item.get("shopify_order_item_id")
		]

		if existing_order_item:
			existing_order_item = existing_order_item[0]
			existing_order_item.qty -= removed.get("delta")
		else:
			# the item should always exist; if it doesn't, log an error
			make_shopify_log(
				shop_name,
				status="Error",
				message=f"Shopify order item {removed.get('id')} not found",
				response_data=order.to_dict(),
			)

	# TODO: process shipping changes
	shipping_lines: Dict = data.get("shipping_lines", {})
	# TODO: update tax lines as well

	update_items(existing_so)


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
	items = []
	for shopify_item in shopify_order_items:
		items.append(get_order_item(shopify_item, shopify_settings))
	return items


def get_order_item(shopify_item: "LineItem", shopify_settings: "ShopifySettings"):
	from shopify_integration.products import get_item_code

	item_code = get_item_code(shopify_item)
	item_group = (
		frappe.db.get_value("Item", item_code, "item_group")
		or shopify_settings.item_group
	)

	stock_uom = shopify_item.attributes.get("uom") or frappe.db.get_single_value(
		"Stock Settings", "stock_uom"
	)

	return {
		"shopify_order_item_id": str(shopify_item.id),
		"item_code": item_code,
		"item_name": shopify_item.attributes.get("name"),
		"item_group": item_group,
		"rate": flt(shopify_item.attributes.get("price")),
		"discount_amount": flt(shopify_item.attributes.get("total_discount")),
		"delivery_date": nowdate(),
		"qty": flt(shopify_item.attributes.get("fulfillable_quantity")),
		"stock_uom": stock_uom,
		"conversion_factor": 1,
		"warehouse": shopify_settings.warehouse,
	}


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
		tax_description = (
			f'{tax.attributes.get("title")} - {tax.attributes.get("rate") * 100.0}%'
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


def cancel_shopify_order(shop_name: str, order_id: str, log_id: str = str()):
	"""
	Cancel all sales documents if a Shopify order is cancelled.

	Args:
		shop_name (str): The name of the Shopify configuration for the store.
		order_id (Order): The Shopify order ID.
		log_id (str, optional): The ID of an existing Shopify Log.
			Defaults to an empty string.
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


def test_run():
	shop = frappe.get_doc("Shopify Settings", "Parsimony Test")
	orders = shop.get_orders()
	from shopify_integration.orders import create_shopify_documents
	create_shopify_documents(shop.name, orders[0].id)
