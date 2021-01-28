# -*- coding: utf-8 -*-
# Copyright (c) 2021, Parsimony, LLC and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt, getdate, now

from shopify_integration.fulfilments import create_shopify_delivery
from shopify_integration.invoices import create_shopify_invoice
from shopify_integration.orders import create_shopify_order
from shopify_integration.shopify_integration.doctype.shopify_log.shopify_log import make_shopify_log
from shopify_integration.utils import get_shopify_document


@frappe.whitelist()
def sync_payouts_from_shopify():
	"""
	Pull and sync payouts from Shopify Payments transactions.
	Can be called manually, otherwise runs daily.
	"""

	if not frappe.db.get_single_value("Shopify Settings", "enable_shopify"):
		return False

	frappe.enqueue(method=create_shopify_payouts, queue='long', is_async=True)
	return True


def create_shopify_payouts():
	"""
	Pull the latest payouts from Shopify and do the following:

		- Create missing Sales Orders, Sales Invoices and Delivery Notes,
			if enabled in Shopify Settings
		- Create a Shopify Payout document with info on all transactions
		- Update any invoices with fees accrued for each payout transaction
	"""

	payouts = get_payouts()
	if not payouts:
		return

	shopify_settings = frappe.get_single("Shopify Settings")

	for payout in payouts:
		if frappe.db.exists("Shopify Payout", {"payout_id": payout.id}):
			continue

		payout_order_ids = []
		try:
			payout_transactions = shopify_settings.get_payout_transactions(payout_id=payout.id)
		except Exception as e:
			make_shopify_log(status="Payout Transactions Error", response_data=payout.to_dict(), exception=e)
		else:
			payout_order_ids = [transaction.source_order_id for transaction in payout_transactions
				if transaction.source_order_id]

		create_missing_orders(payout_order_ids)
		payout_doc = create_shopify_payout(payout)
		payout_doc.update_invoice_fees()

	shopify_settings.last_sync_datetime = now()
	shopify_settings.save()


def get_payouts():
	"""
	Request Shopify API for the latest payouts

	Returns:
		list of shopify.Payout: The list of Shopify payouts, if any.
	"""

	shopify_settings = frappe.get_single("Shopify Settings")

	kwargs = {}
	if shopify_settings.last_sync_datetime:
		kwargs['date_min'] = shopify_settings.last_sync_datetime

	try:
		payouts = shopify_settings.get_payouts(**kwargs)
	except Exception as e:
		make_shopify_log(status="Payout Error", exception=e, rollback=True)
		return []
	else:
		return payouts


def create_missing_orders(shopify_order_ids):
	"""
	Create missing Sales Orders, Sales Invoices and Delivery Notes,
		if enabled in Shopify Settings.

	Args:
		shopify_order_ids (list of str): The Shopify order IDs to create documents against
	"""

	settings = frappe.get_single("Shopify Settings")

	for shopify_order_id in shopify_order_ids:
		sales_order = get_shopify_document("Sales Order", shopify_order_id)
		sales_invoice = get_shopify_document("Sales Invoice", shopify_order_id)
		delivery_note = get_shopify_document("Delivery Note", shopify_order_id)

		if all([sales_order, sales_invoice, delivery_note]):
			continue

		orders = settings.get_orders(shopify_order_id)
		if not orders:
			continue

		order = orders[0]

		# create an order, invoice and delivery, if missing
		if not sales_order:
			sales_order = create_shopify_order(order.to_dict())

		if sales_order:
			if not sales_invoice:
				create_shopify_invoice(order.to_dict(), sales_order)
			if not delivery_note:
				create_shopify_delivery(order.to_dict(), sales_order)


def create_shopify_payout(payout):
	"""
	Create a Shopify Payout document from Shopify's Payout information.

	Args:
		payout (shopify.Payout): The Payout payload from Shopify

	Returns:
		ShopifyPayout: The created Shopify Payout document
	"""

	company = frappe.db.get_single_value("Shopify Settings", "company")
	settings = frappe.get_single("Shopify Settings")

	payout_doc = frappe.new_doc("Shopify Payout")
	payout_doc.update({
		"company": company,
		"payout_id": payout.id,
		"payout_date": getdate(payout.date),
		"status": frappe.unscrub(payout.status),
		"amount": flt(payout.amount),
		"currency": payout.currency,
		**payout.summary.to_dict()  # unpack the payout amounts and fees from the summary
	})

	try:
		payout_transactions = settings.get_payout_transactions(payout_id=payout.id)
	except Exception as e:
		payout_doc.save()
		make_shopify_log(status="Payout Transactions Error", response_data=payout.to_dict(), exception=e)
		return payout_doc

	payout_doc.set("transactions", [])
	for transaction in payout_transactions:
		shopify_order_id = transaction.source_order_id

		order_financial_status = None
		if shopify_order_id:
			orders = settings.get_orders(shopify_order_id)
			if not orders:
				continue
			order = orders[0]
			order_financial_status = frappe.unscrub(order.financial_status)

		total_amount = -flt(transaction.amount) if transaction.type == "payout" else flt(transaction.amount)
		net_amount = -flt(transaction.net) if transaction.type == "payout" else flt(transaction.net)

		sales_order = get_shopify_document("Sales Order", shopify_order_id)
		sales_invoice = get_shopify_document("Sales Invoice", shopify_order_id)
		delivery_note = get_shopify_document("Delivery Note", shopify_order_id)

		payout_doc.append("transactions", {
			"transaction_id": transaction.id,
			"transaction_type": frappe.unscrub(transaction.type),
			"processed_at": getdate(transaction.processed_at),
			"total_amount": total_amount,
			"fee": flt(transaction.fee),
			"net_amount": net_amount,
			"currency": transaction.currency,
			"sales_order": sales_order.name if sales_order else None,
			"sales_invoice": sales_invoice.name if sales_invoice else None,
			"delivery_note": delivery_note.name if delivery_note else None,
			"source_id": transaction.source_id,
			"source_type": frappe.unscrub(transaction.source_type),
			"source_order_financial_status": order_financial_status,
			"source_order_id": shopify_order_id,
			"source_order_transaction_id": transaction.source_order_transaction_id,
		})

	payout_doc.save()
	frappe.db.commit()
	return payout_doc
