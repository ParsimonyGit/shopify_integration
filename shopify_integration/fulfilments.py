import frappe
from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
from frappe.utils import cint, cstr, getdate

from shopify_integration.products import get_item_code
from shopify_integration.shopify_integration.doctype.shopify_log.shopify_log import make_shopify_log
from shopify_integration.utils import get_shopify_document


def prepare_delivery_note(order, request_id=None):
	frappe.set_user("Administrator")
	frappe.flags.request_id = request_id

	try:
		sales_order = get_shopify_document("Sales Order", cstr(order.get("id")))
		if sales_order:
			create_delivery_notes(order, sales_order)
		make_shopify_log(status="Success", response_data=order)
	except Exception as e:
		make_shopify_log(status="Error", response_data=order, exception=e, rollback=True)


def create_shopify_delivery(order, so, request_id=None):
	frappe.flags.request_id = request_id

	if not order.get("fulfillments"):
		return

	try:
		delivery_notes = create_delivery_notes(order, so)
	except Exception as e:
		make_shopify_log(status="Error", response_data=order, exception=e)
		return
	else:
		return delivery_notes


def create_delivery_notes(shopify_order, so):
	shopify_settings = frappe.get_doc("Shopify Settings")
	if not cint(shopify_settings.sync_delivery_note):
		return

	delivery_notes = []
	for fulfillment in shopify_order.get("fulfillments"):
		if so.docstatus == 1 and not frappe.db.get_value("Delivery Note",
			{"shopify_fulfillment_id": fulfillment.get("id")}, "name"):

			dn = make_delivery_note(so.name)
			dn.shopify_order_id = shopify_order.get("id")
			dn.shopify_order_number = shopify_order.get("name")
			dn.shopify_fulfillment_id = fulfillment.get("id")
			dn.set_posting_time = 1
			dn.posting_date = getdate(fulfillment.get("created_at"))
			dn.naming_series = shopify_settings.delivery_note_series or "DN-Shopify-"
			dn.items = get_fulfillment_items(dn.items, fulfillment.get("line_items"))
			dn.flags.ignore_mandatory = True
			dn.save()
			dn.submit()
			frappe.db.commit()
			delivery_notes.append(dn)

	return delivery_notes


def get_fulfillment_items(dn_items, fulfillment_items):
	# TODO: figure out a better way to add items without setting valuation rate to zero
	return [dn_item.update({"qty": item.get("quantity"), "allow_zero_valuation_rate": 1})
		for item in fulfillment_items for dn_item in dn_items
		if get_item_code(item) == dn_item.item_code]
