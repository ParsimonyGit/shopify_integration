from typing import TYPE_CHECKING, List

import frappe
from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
from frappe.utils import cint, getdate

from shopify_integration.orders import get_shopify_order
from shopify_integration.products import get_item_code
from shopify_integration.shopify_integration.doctype.shopify_log.shopify_log import make_shopify_log
from shopify_integration.utils import get_shopify_document

if TYPE_CHECKING:
	from erpnext.selling.doctype.sales_order.sales_order import SalesOrder
	from erpnext.stock.doctype.delivery_note.delivery_note import DeliveryNote
	from shopify import Fulfillment, LineItem, Order
	from shopify_integration.shopify_integration.doctype.shopify_settings.shopify_settings import ShopifySettings


def prepare_delivery_note(shop_name: str, order_id: str, log_id: str = str()):
	"""
	Webhook endpoint to process deliveries for Shopify orders.

	Args:
		shop_name (str): The name of the Shopify configuration for the store.
		order_id (str): The Shopify order ID.
		log_id (str, optional): The ID of an existing Shopify Log.
			Defaults to an empty string.
	"""

	frappe.set_user("Administrator")
	frappe.flags.log_id = log_id

	order = get_shopify_order(shop_name, order_id, log_id)
	if not order:
		return

	create_shopify_delivery(shop_name=shop_name, shopify_order=order, log_id=log_id, rollback=True)


def create_shopify_delivery(
	shop_name: str,
	shopify_order: "Order",
	sales_order: "SalesOrder" = None,
	log_id: str = str(),
	rollback: bool = False
):
	"""
	Create Delivery Note documents for each Shopify delivery.

	Args:
		shop_name (str): The name of the Shopify configuration for the store.
		shopify_order (Order): The Shopify order data.
		sales_order (SalesOrder, optional): The reference Sales Order document for the
			Shopify order. Defaults to None.
		log_id (str, optional): The ID of an existing Shopify Log. Defaults to an empty string.
		rollback (bool, optional): If an error occurs while processing the order, all
			transactions will be rolled back, if this field is `True`. Defaults to False.

	Returns:
		list: The list of created Delivery Note documents, if any, otherwise an empty list.
	"""

	if not shopify_order.attributes.get("fulfillments"):
		return []
	if not sales_order:
		sales_order = get_shopify_document(shop_name=shop_name, doctype="Sales Order", order=shopify_order)
	if not sales_order or sales_order.docstatus != 1:
		return []

	frappe.flags.log_id = log_id
	try:
		delivery_notes = create_delivery_notes(shop_name, shopify_order, sales_order)
	except Exception as e:
		make_shopify_log(shop_name, status="Error", response_data=shopify_order.to_dict(), exception=e, rollback=rollback)
		return []
	else:
		make_shopify_log(shop_name, status="Success", response_data=shopify_order.to_dict())
		return delivery_notes


def create_delivery_notes(
	shop_name: str,
	shopify_order: "Order",
	sales_order: "SalesOrder"
) -> List["DeliveryNote"]:
	"""
	Helper function to create Delivery Note documents for a Shopify order.

	Args:
		shop_name (str): The name of the Shopify configuration for the store.
		shopify_order (Order): The Shopify order data.
		sales_order (SalesOrder): The reference Sales Order document for the Shopify order.

	Returns:
		list: The list of created Delivery Note documents, if any, otherwise an empty list.
	"""

	shopify_settings: "ShopifySettings" = frappe.get_doc("Shopify Settings", shop_name)
	if not cint(shopify_settings.sync_delivery_note):
		return []

	delivery_notes = []
	shopify_order_name = shopify_order.attributes.get("name")
	shopify_order_name = shopify_order_name.split("#")[-1]

	fulfillment: "Fulfillment"
	for fulfillment in shopify_order.attributes.get("fulfillments"):
		existing_delivery = frappe.db.get_value("Delivery Note",
			{"docstatus": 1, "shopify_fulfillment_id": fulfillment.id}, "name")

		if not existing_delivery:
			dn: "DeliveryNote" = make_delivery_note(source_name=sales_order.name, skip_item_mapping=True)
			dn.update({
				"shopify_settings": shopify_settings.name,
				"shopify_order_id": shopify_order.id,
				"shopify_order_number": shopify_order.attributes.get("order_number"),
				"shopify_order_name": shopify_order_name,
				"shopify_fulfillment_id": fulfillment.id,
				"set_posting_time": True,
				"posting_date": getdate(fulfillment.attributes.get("created_at")),
				"naming_series": shopify_settings.delivery_note_series or "DN-Shopify-",
			})

			dn.flags.ignore_mandatory = True
			dn_items = update_fulfillment_items(sales_order, fulfillment.attributes.get("line_items"))
			dn.items = dn_items
			dn.save()
			dn.submit()
			frappe.db.commit()
			delivery_notes.append(dn)

	return delivery_notes


def update_fulfillment_items(
	so: List["SalesOrder"],
	fulfillment_items: List["LineItem"],
):
	dn_items= []
	for so_item in so.items:
		# TODO: figure out a better way to add items without setting valuation rate to zero
		for item in fulfillment_items:
			if get_item_code(item) == so_item.item_code:
				dn_item = frappe.new_doc("Delivery Note Item")
				dn_item.update({
					"allow_zero_valuation_rate": True, # is it necesarry now? #L151
					"item_code": so_item.item_code,
					"item_name": so_item.item_name,
					"description": so_item.description,
					"qty": item.attributes.get("quantity"),
					"rate": so_item.rate,
					"against_sales_order": so.name,
					"shopify_order_item_id": item.attributes.get("id"),
					"parenttype": "Delivery Note",
					"parentfield": "items",
				})
				dn_items.append(dn_item)

	return dn_items

