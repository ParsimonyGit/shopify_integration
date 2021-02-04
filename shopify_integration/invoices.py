import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
from frappe.utils import cint, cstr, flt, get_datetime, getdate

from shopify_integration.orders import sync_sales_order
from shopify_integration.shopify_integration.doctype.shopify_log.shopify_log import make_shopify_log
from shopify_integration.utils import get_shopify_document, get_tax_account_head


def prepare_sales_invoice(order, request_id=None):
	frappe.set_user('Administrator')
	frappe.flags.request_id = request_id

	try:
		sales_order = get_shopify_document("Sales Order", cstr(order.get('id')))
		if not sales_order:
			sync_sales_order(order, request_id)
			sales_order = get_shopify_document("Sales Order", cstr(order.get('id')))

		if sales_order:
			create_sales_invoice(order, sales_order)
			make_shopify_log(status="Success", response_data=order)
	except Exception as e:
		make_shopify_log(status="Error", response_data=order, exception=e, rollback=True)


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
