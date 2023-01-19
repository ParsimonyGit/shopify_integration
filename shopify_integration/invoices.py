from typing import TYPE_CHECKING

import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
from frappe.utils import cint, flt, get_datetime, getdate

from shopify_integration.orders import get_shopify_order
from shopify_integration.shopify_integration.doctype.shopify_log.shopify_log import make_shopify_log
from shopify_integration.utils import get_shopify_document, get_tax_account_head

if TYPE_CHECKING:
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
	from erpnext.selling.doctype.sales_order.sales_order import SalesOrder
	from shopify import Order
	from shopify_integration.shopify_integration.doctype.shopify_settings.shopify_settings import ShopifySettings


def prepare_sales_invoice(shop_name: str, order_id: str, log_id: str = str()):
	"""
	Webhook endpoint to process invoices for Shopify orders.

	Args:
		shop_name (str): The name of the Shopify configuration for the store.
		order_id (Order): The Shopify order ID.
		log_id (str, optional): The ID of an existing Shopify Log.
			Defaults to an empty string.
	"""

	from shopify_integration.orders import create_shopify_documents

	frappe.set_user("Administrator")
	frappe.flags.log_id = log_id

	order = get_shopify_order(shop_name, order_id, log_id)
	if not order:
		return

	try:
		sales_order = get_shopify_document(shop_name=shop_name, doctype="Sales Order", order=order)
		if not sales_order:
			create_shopify_documents(shop_name, order, log_id)
			sales_order = get_shopify_document(shop_name=shop_name, doctype="Sales Order", order=order)

		if sales_order:
			sales_order: "SalesOrder"
			create_sales_invoice(shop_name, order, sales_order)
			make_shopify_log(shop_name, status="Success", response_data=order.to_dict())
		else:
			make_shopify_log(shop_name, status="Skipped", response_data=order.to_dict())
	except Exception as e:
		make_shopify_log(shop_name, status="Error", response_data=order.to_dict(), exception=e, rollback=True)


def create_shopify_invoice(
	shop_name: str,
	shopify_order: "Order",
	sales_order: "SalesOrder",
	log_id: str = str()
):
	"""
	Create a Sales Invoice document for a Shopify order. If the Shopify order is refunded
	and a submitted Sales Invoice exists, make a sales return against the invoice.

	Args:
		shop_name (str): The name of the Shopify configuration for the store.
		shopify_order (Order): The Shopify order data.
		sales_order (SalesOrder, optional): The reference Sales Order document for the
			Shopify order. Defaults to None.
		log_id (str, optional): The ID of an existing Shopify Log. Defaults to an empty string.

	Returns:
		SalesInvoice: The created Sales Invoice document, if any, otherwise None.
	"""

	if not shopify_order.attributes.get("financial_status") in ["paid", "partially_refunded", "refunded"]:
		return

	frappe.flags.log_id = log_id
	try:
		sales_invoice = create_sales_invoice(shop_name, shopify_order, sales_order)
		if sales_invoice and sales_invoice.docstatus == 1:
			create_sales_return(
				shop_name=shop_name,
				shopify_order_id=shopify_order.id,
				shopify_financial_status=shopify_order.attributes.get("financial_status"),
				sales_invoice=sales_invoice
			)
	except Exception as e:
		make_shopify_log(shop_name, status="Error", response_data=shopify_order.to_dict(), exception=e)
	else:
		make_shopify_log(shop_name, status="Success", response_data=shopify_order.to_dict())
		return sales_invoice


def create_sales_invoice(shop_name: str, shopify_order: "Order", sales_order: "SalesOrder"):
	"""
	Helper function to create a Sales Invoice document for a Shopify order.

	Args:
		shop_name (str): The name of the Shopify configuration for the store.
		shopify_order (Order): The Shopify order data.
		sales_order (SalesOrder): The reference Sales Order document for the Shopify order.

	Returns:
		SalesInvoice: The created or existing Sales Invoice document, if any, otherwise None.
	"""

	shopify_settings: "ShopifySettings" = frappe.get_doc("Shopify Settings", shop_name)
	if not cint(shopify_settings.sync_sales_invoice):
		return

	existing_invoice = get_shopify_document(shop_name=shop_name, doctype="Sales Invoice", order=shopify_order)
	if existing_invoice:
		existing_invoice: "SalesInvoice"
		frappe.db.set_value("Sales Invoice", existing_invoice.name, {
			"shopify_settings": shopify_settings.name,
			"shopify_order_id": shopify_order.id,
			"shopify_order_number": shopify_order.attributes.get("order_number")
		})
		return existing_invoice

	if sales_order.docstatus == 1 and not sales_order.per_billed:
		sales_invoice: "SalesInvoice" = make_sales_invoice(sales_order.name, ignore_permissions=True)
		sales_invoice.update({
			"shopify_settings": shopify_settings.name,
			"shopify_order_id": shopify_order.id,
			"shopify_order_number": shopify_order.attributes.get("order_number"),
			"set_posting_time": True,
			"posting_date": getdate(shopify_order.attributes.get("created_at")),
			"naming_series": shopify_settings.sales_invoice_series or "SI-Shopify-"
		})

		for item in sales_invoice.items:
			item.cost_center = shopify_settings.cost_center

		sales_invoice.flags.ignore_mandatory = True
		sales_invoice.insert(ignore_mandatory=True)
		frappe.db.commit()
		return sales_invoice


def create_sales_return(
	shop_name: str,
	shopify_order_id: int,
	shopify_financial_status: str,
	sales_invoice: "SalesInvoice"
):
	"""
	Create a Sales Invoice return for the given Shopify order.

	Args:
		shop_name (str): The name of the Shopify configuration for the store.
		shopify_order_id (int): The Shopify order ID.
		shopify_financial_status (str): The financial status of the Shopify order.
			Should be one of: refunded, partially_refunded.
		sales_invoice (SalesInvoice): The Sales Invoice document.

	Returns:
		SalesInvoice: The Sales Invoice return document.
			If no refunds are found, returns None.
	"""

	shopify_settings: "ShopifySettings" = frappe.get_doc("Shopify Settings", shop_name)
	refunds = shopify_settings.get_refunds(order_id=shopify_order_id)

	refund_dates = [refund.processed_at or refund.created_at
		for refund in refunds if refund.processed_at or refund.created_at]

	if not refund_dates:
		return

	refund_datetime = min(get_datetime(date) for date in refund_dates)
	if not refund_datetime:
		return

	return_invoice: "SalesInvoice" = make_sales_return(sales_invoice.name)
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
					"account_head": get_tax_account_head(shop_name, "refund"),
					"description": adjustment.reason,
					"tax_amount": flt(adjustment.amount)
				})

	return_invoice.save()
	return_invoice.submit()
	return return_invoice
