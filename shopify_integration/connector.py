import json

import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
from erpnext.erpnext_integrations.utils import validate_webhooks_request
from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note, make_sales_invoice
from frappe import _
from frappe.utils import cint, cstr, flt, getdate, get_datetime, nowdate

from shopify_integration.shopify_integration.doctype.shopify_log.shopify_log import dump_request_data, make_shopify_log
from shopify_integration.shopify_integration.doctype.shopify_settings.sync_customer import create_customer
from shopify_integration.shopify_integration.doctype.shopify_settings.sync_product import make_item


@frappe.whitelist(allow_guest=True)
@validate_webhooks_request("Shopify Settings", 'X-Shopify-Hmac-Sha256', secret_key='shared_secret')
def store_request_data(order=None, event=None):
	if frappe.request:
		order = json.loads(frappe.request.data)
		event = frappe.request.headers.get('X-Shopify-Topic')

	dump_request_data(order, event)


def sync_sales_order(order, request_id=None):
	"""
	Create the following from a Shopify order:

		- Sales Order
		- Sales Invoice (if paid)
		- Delivery Note (if fulfilled)

	Args:

		order (dict): The Shopify order data.
		request_id (str, optional): The ID of the existing Shopify Log document
			for this request. Defaults to None.
	"""

	frappe.set_user('Administrator')
	frappe.flags.request_id = request_id
	so = create_shopify_order(order, request_id)
	if so:
		create_shopify_invoice(order, so, request_id)
		create_shopify_delivery(order, so, request_id)


def create_shopify_order(order, request_id=None):
	frappe.flags.request_id = request_id

	existing_so = frappe.db.get_value("Sales Order",
		filters={
			"docstatus": ["<", 2],
			"shopify_order_id": cstr(order.get('id'))
		})

	if existing_so:
		return frappe.get_doc("Sales Order", existing_so)

	try:
		validate_customer(order)
		validate_item(order)
		so = create_sales_order(order)
	except Exception as e:
		make_shopify_log(status="Error", response_data=order, exception=e)
	else:
		make_shopify_log(status="Success", response_data=order)
		return so


def create_shopify_invoice(order, so, request_id=None):
	frappe.flags.request_id = request_id

	if not order.get("financial_status") in ["paid", "partially_refunded", "refunded"]:
		return

	try:
		si = create_sales_invoice(order, so)
		if si:
			create_sales_return(order.get("id"), order.get("financial_status"), si)
	except Exception as e:
		make_shopify_log(status="Error", response_data=order, exception=e)
	else:
		return si


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


def prepare_sales_invoice(order, request_id=None):
	frappe.set_user('Administrator')
	frappe.flags.request_id = request_id

	try:
		sales_order = get_shopify_document("Sales Order", cstr(order.get('id')))
		if sales_order:
			create_sales_invoice(order, sales_order)
			make_shopify_log(status="Success", response_data=order)
	except Exception as e:
		make_shopify_log(status="Error", response_data=order, exception=e, rollback=True)


def prepare_delivery_note(order, request_id=None):
	frappe.set_user('Administrator')
	frappe.flags.request_id = request_id

	try:
		sales_order = get_shopify_document("Sales Order", cstr(order.get('id')))
		if sales_order:
			create_delivery_notes(order, sales_order)
		make_shopify_log(status="Success", response_data=order)
	except Exception as e:
		make_shopify_log(status="Error", response_data=order, exception=e, rollback=True)


def cancel_shopify_order(order, request_id=None):
	frappe.set_user('Administrator')
	frappe.flags.request_id = request_id

	doctypes = ["Delivery Note", "Sales Invoice", "Sales Order"]
	for doctype in doctypes:
		doc = get_shopify_document(doctype, cstr(order.get('id')))
		if doc:
			try:
				doc.cancel()
			except Exception as e:
				make_shopify_log(status="Error", response_data=order,
					exception=e, rollback=True)


def validate_customer(order):
	customer_id = order.get("customer", {}).get("id")
	if customer_id:
		if not frappe.db.get_value("Customer", {"shopify_customer_id": customer_id}, "name"):
			create_customer(order.get("customer"))


def validate_item(order):
	for item in order.get("line_items"):
		product_id = item.get("product_id")
		if product_id and not frappe.db.exists("Item", {"shopify_product_id": product_id}):
			make_item(item)

		# Shopify somehow allows non-existent variants to be added to an order;
		# for such cases, we force-create the item after creating the other variants
		variant_id = item.get("variant_id")
		if variant_id and not frappe.db.exists("Item", {"shopify_variant_id": variant_id}):
			make_item(item)


def create_sales_order(shopify_order, company=None):
	shopify_settings = frappe.get_single("Shopify Settings")

	customer = frappe.db.get_value("Customer", {"shopify_customer_id": shopify_order.get("customer", {}).get("id")}, "name")
	so = frappe.db.get_value("Sales Order", {"docstatus": ["<", 2], "shopify_order_id": shopify_order.get("id")}, "name")

	if not so:
		items = get_order_items(shopify_order.get("line_items"), shopify_settings)

		so = frappe.get_doc({
			"doctype": "Sales Order",
			"naming_series": shopify_settings.sales_order_series or "SO-Shopify-",
			"shopify_order_id": shopify_order.get("id"),
			"customer": customer or shopify_settings.default_customer,
			"delivery_date": nowdate(),
			"company": shopify_settings.company,
			"selling_price_list": shopify_settings.price_list,
			"ignore_pricing_rule": 1,
			"items": items,
			"taxes": get_order_taxes(shopify_order, shopify_settings),
			"apply_discount_on": "Grand Total",
			"discount_amount": flt(shopify_order.get("total_discounts")),
		})

		if company:
			so.update({
				"company": company,
				"status": "Draft"
			})
		so.flags.ignore_mandatory = True
		so.save(ignore_permissions=True)
		so.submit()

	else:
		so = frappe.get_doc("Sales Order", so)

	frappe.db.commit()
	return so


def create_sales_invoice(shopify_order, sales_order):
	shopify_settings = frappe.get_single("Shopify Settings")
	if not cint(shopify_settings.sync_sales_invoice):
		return

	si = get_shopify_document("Sales Invoice", shopify_order.get("id"))
	if not si and sales_order.docstatus == 1 and not sales_order.per_billed:
		si = make_sales_invoice(sales_order.name, ignore_permissions=True)
		si.shopify_order_id = shopify_order.get("id")
		si.shopify_order_number = shopify_order.get("name")
		si.set_posting_time = 1
		si.posting_date = getdate(shopify_order.get('created_at'))
		si.naming_series = shopify_settings.sales_invoice_series or "SI-Shopify-"
		si.flags.ignore_mandatory = True
		set_cost_center(si.items, shopify_settings.cost_center)
		si.insert(ignore_mandatory=True)
		frappe.db.commit()
		return si


def create_sales_return(shopify_order_id, shopify_financial_status, sales_invoice):
	"""
	Create a Sales Invoice return for the given Shopify order

	Args:
		shopify_order_id (int): The Shopify order ID.
		shopify_financial_status (str): The financial status of the Shopify order.
			Should be one of: refunded, partially_refunded.
		sales_invoice (SalesInvoice): The Sales Invoice document.

	Returns:
		SalesInvoice: The Sales Invoice return document.
			If no refunds are found, return None.
	"""

	shopify_settings = frappe.get_single("Shopify Settings")
	refunds = shopify_settings.get_refunds(order_id=shopify_order_id)

	refund_dates = [refund.processed_at or refund.created_at for refund in refunds
		if refund.processed_at or refund.created_at]
	if not refund_dates:
		return

	refund_datetime = min([get_datetime(date) for date in refund_dates]) if refund_dates else None
	if not refund_datetime:
		return

	return_invoice = make_sales_return(sales_invoice.name)
	return_invoice.set_posting_time = True
	return_invoice.posting_date = refund_datetime.date()
	return_invoice.posting_time = refund_datetime.time()

	if shopify_financial_status == "partially_refunded":
		for refund in refunds:
			refunded_items = [item.line_item.product_id for item in refund.refund_line_items
				if item.line_item.product_id]
			refunded_variants = [item.line_item.variant_id for item in refund.refund_line_items
				if item.line_item.variant_id]

			for item in return_invoice.items:
				# for partial refunds, check each item for refunds
				shopify_product_id = frappe.db.get_value("Item", item.item_code, "shopify_product_id")
				shopify_variant_id = frappe.db.get_value("Item", item.item_code, "shopify_variant_id")
				if shopify_product_id in refunded_items or shopify_variant_id in refunded_variants:
					continue

				# set item values for non-refunded items to zero;
				# preferring this over removal of the item to avoid zero-item
				# refunds and downstream effects for other documents
				item.qty = 0
				item.discount_percentage = 100

			# add any additional adjustments as charges
			return_invoice.set("taxes", [])
			adjustments = refund.order_adjustments
			for adjustment in adjustments:
				return_invoice.append("taxes", {
					"charge_type": "Actual",
					"account_head": get_tax_account_head("refund"),
					"description": adjustment.reason,
					"tax_amount": flt(adjustment.amount)
				})

	return_invoice.save()
	return_invoice.submit()
	return return_invoice


def set_cost_center(items, cost_center):
	for item in items:
		item.cost_center = cost_center


def create_delivery_notes(shopify_order, so):
	shopify_settings = frappe.get_doc("Shopify Settings")
	if not cint(shopify_settings.sync_delivery_note):
		return

	delivery_notes = []
	for fulfillment in shopify_order.get("fulfillments"):
		if not frappe.db.get_value("Delivery Note", {"shopify_fulfillment_id": fulfillment.get("id")}, "name")\
			and so.docstatus == 1:

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


def get_order_items(order_items, shopify_settings):
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


def get_item_code(shopify_item):
	item_code = frappe.db.get_value("Item", {"shopify_variant_id": shopify_item.get("variant_id")}, "item_code")
	if not item_code:
		item_code = frappe.db.get_value("Item",
			{"shopify_product_id": shopify_item.get("product_id") or shopify_item.get("id")}, "item_code")
	if not item_code:
		item_code = frappe.db.get_value("Item", {"item_name": shopify_item.get("title")}, "item_code")

	return item_code


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
