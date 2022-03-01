# -*- coding: utf-8 -*-
# Copyright (c) 2021, Parsimony, LLC and contributors
# For license information, please see license.txt

from typing import TYPE_CHECKING, List

import frappe
from frappe.utils import flt, get_datetime_str, get_first_day, getdate, now, today

from shopify_integration.fulfilments import create_shopify_delivery
from shopify_integration.invoices import create_shopify_invoice
from shopify_integration.orders import create_shopify_order
from shopify_integration.shopify_integration.doctype.shopify_log.shopify_log import make_shopify_log
from shopify_integration.utils import get_shopify_document

if TYPE_CHECKING:
	from erpnext.selling.doctype.sales_order.sales_order import SalesOrder
	from shopify import Order, Payouts, Transactions
	from shopify_integration.shopify_integration.doctype.shopify_settings.shopify_settings import ShopifySettings
	from shopify_integration.shopify_integration.doctype.shopify_payout.shopify_payout import ShopifyPayout


def sync_all_payouts():
	"""
	Daily hook to sync payouts from Shopify Payments transactions in all Shopify stores.
	"""

	for shop in frappe.get_all("Shopify Settings", filters={"enable_shopify": True}):
		shop_doc: "ShopifySettings" = frappe.get_doc("Shopify Settings", shop.name)
		shop_doc.sync_payouts()


def create_shopify_payouts(shop_name: str, start_date: str = str()):
	"""
	Pull the latest payouts from Shopify and do the following:

		- Create missing Sales Orders, Sales Invoices and Delivery Notes,
			if enabled in Shopify Settings
		- Create a Shopify Payout document with info on all transactions
		- Update any invoices with fees accrued for each payout transaction

	Args:
		shop_name (str): The name of the Shopify configuration for the store.
		start_date (str, optional): The date to start pulling payouts from.
	"""

	shopify_settings: "ShopifySettings" = frappe.get_doc("Shopify Settings", shop_name)

	payouts = get_payouts(shopify_settings, start_date)
	if not payouts:
		return

	for payout in payouts:
		if frappe.db.exists("Shopify Payout", {"payout_id": payout.id}):
			continue

		payout_order_ids = []
		try:
			payout_transactions: List["Transactions"] = shopify_settings.get_payout_transactions(
				payout_id=payout.id
			)
		except Exception as e:
			make_shopify_log(
				shop_name=shop_name,
				status="Payout Transactions Error",
				response_data=payout.to_dict(),
				exception=e
			)
		else:
			payout_order_ids = [transaction.source_order_id for transaction in payout_transactions
				if transaction.source_order_id]

		create_missing_orders(shopify_settings, payout_order_ids)
		payout_doc: "ShopifyPayout" = create_shopify_payout(shopify_settings, payout)
		payout_doc.update_invoice_fees()

	shopify_settings.last_sync_datetime = now()
	shopify_settings.save()


def get_payouts(shopify_settings: "ShopifySettings", start_date: str = str()):
	"""
	Request Shopify API for the latest payouts

	Args:
		shopify_settings (ShopifySettings): The Shopify configuration for the store.
		start_date (str, optional): The date to start pulling payouts from.

	Returns:
		list of shopify.Payout: The list of Shopify payouts, if any.
	"""

	kwargs = {}
	if start_date:
		kwargs['date_min'] = start_date
	elif shopify_settings.last_sync_datetime:
		kwargs['date_min'] = shopify_settings.last_sync_datetime
	else:
		# default to first day of current month for first sync
		kwargs['date_min'] = get_datetime_str(get_first_day(today()))

	try:
		payouts = shopify_settings.get_payouts(**kwargs)
	except Exception as e:
		make_shopify_log(shopify_settings.name, status="Payout Error", exception=e, rollback=True)
		return []
	else:
		return payouts


def create_missing_orders(shopify_settings: "ShopifySettings", shopify_order_ids: List[str]):
	"""
	Create missing Sales Orders, Sales Invoices and Delivery Notes, if enabled in Shopify Settings.

	Args:
		shopify_settings (ShopifySettings): The Shopify configuration for the store.
		shopify_order_ids (list of str): The Shopify order IDs to create documents against.
	"""

	for shopify_order_id in shopify_order_ids:
		sales_order = get_shopify_document(shop_name=shopify_settings.name,
			doctype="Sales Order", order_id=shopify_order_id)
		sales_invoice = get_shopify_document(shop_name=shopify_settings.name,
			doctype="Sales Invoice", order_id=shopify_order_id)
		delivery_note = get_shopify_document(shop_name=shopify_settings.name,
			doctype="Delivery Note", order_id=shopify_order_id)

		if all([sales_order, sales_invoice, delivery_note]):
			continue

		orders = shopify_settings.get_orders(shopify_order_id)
		if not orders:
			continue

		order: "Order" = orders[0]

		# create an order, invoice and delivery, if missing
		if not sales_order:
			sales_order = create_shopify_order(shopify_settings.name, order)

		if sales_order:
			sales_order: "SalesOrder"
			if not sales_invoice:
				create_shopify_invoice(shopify_settings.name, order, sales_order)
			if not delivery_note or sales_order.per_delivered < 100:
				# multiple deliveries can be made against a single order
				create_shopify_delivery(shopify_settings.name, order, sales_order)


def create_shopify_payout(shopify_settings: "ShopifySettings", payout: "Payouts"):
	"""
	Create a Shopify Payout document from Shopify's Payout information.

	Args:
		shopify_settings (ShopifySettings): The Shopify configuration for the store.
		payout (Payouts): The Payout payload from Shopify.

	Returns:
		ShopifyPayout: The created Shopify Payout document.
	"""

	payout_doc: "ShopifyPayout" = frappe.new_doc("Shopify Payout")
	payout_doc.update({
		"shop_name": shopify_settings.name,
		"company": shopify_settings.company,
		"payout_id": payout.id,
		"payout_date": getdate(payout.date),
		"status": frappe.unscrub(payout.status),
		"amount": flt(payout.amount),
		"currency": payout.currency,
		**payout.summary.to_dict()  # unpack the payout amounts and fees from the summary
	})

	try:
		payout_transactions: List["Transactions"] = shopify_settings.get_payout_transactions(payout_id=payout.id)
	except Exception as e:
		payout_doc.save(ignore_permissions=True)
		make_shopify_log(shopify_settings.name, status="Payout Transactions Error", response_data=payout.to_dict(), exception=e)
		return payout_doc

	payout_doc.set("transactions", [])
	for transaction in payout_transactions:
		shopify_order_id = transaction.source_order_id

		order_financial_status = sales_order = sales_invoice = delivery_note = None
		if shopify_order_id:
			orders = shopify_settings.get_orders(shopify_order_id)
			if not orders:
				continue
			order = orders[0]
			order_financial_status = frappe.unscrub(order.financial_status)

			sales_order = get_shopify_document(shop_name=shopify_settings.name,
				doctype="Sales Order", order_id=shopify_order_id)
			sales_invoice = get_shopify_document(shop_name=shopify_settings.name,
				doctype="Sales Invoice", order_id=shopify_order_id)
			delivery_note = get_shopify_document(shop_name=shopify_settings.name,
				doctype="Delivery Note", order_id=shopify_order_id)

		total_amount = -flt(transaction.amount) if transaction.type == "payout" else flt(transaction.amount)
		net_amount = -flt(transaction.net) if transaction.type == "payout" else flt(transaction.net)

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
			"source_type": frappe.unscrub(transaction.source_type or ""),
			"source_order_financial_status": order_financial_status,
			"source_order_id": shopify_order_id,
			"source_order_transaction_id": transaction.source_order_transaction_id,
		})

	payout_doc.save(ignore_permissions=True)
	frappe.db.commit()
	return payout_doc
