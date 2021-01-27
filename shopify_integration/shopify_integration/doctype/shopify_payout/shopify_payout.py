# -*- coding: utf-8 -*-
# Copyright (c) 2021, Parsimony, LLC and contributors
# For license information, please see license.txt

from collections import defaultdict

import frappe
from erpnext.controllers.accounts_controller import get_accounting_entry
from frappe.model.document import Document
from frappe.utils import cint, flt

from shopify_integration.connector import create_sales_return, get_tax_account_head
from shopify_integration.shopify_integration.doctype.shopify_log.shopify_log import make_shopify_log


class ShopifyPayout(Document):
	def on_submit(self):
		"""
		On submit of a Payout, do the following:

			- If a Shopify Order is cancelled, update all linked documents in ERPNext
			- If a Shopify Order has been fully or partially returned, make a
				sales return in ERPNext
			- Create a Journal Entry to balance all existing transactions
				with additional fees and charges from Shopify, if any
		"""

		self.update_cancelled_shopify_orders()
		self.create_sales_returns()
		self.create_payout_journal_entry()

	def update_cancelled_shopify_orders(self):
		doctypes = ["Delivery Note", "Sales Invoice", "Sales Order"]
		settings = frappe.get_single("Shopify Settings")

		for transaction in self.transactions:
			if not transaction.source_order_id:
				continue

			shopify_orders = settings.get_orders(cint(transaction.source_order_id))
			if not shopify_orders:
				continue

			shopify_order = shopify_orders[0]
			if not shopify_order.cancelled_at:
				continue

			for doctype in doctypes:
				doctype_field = frappe.scrub(doctype)
				docname = transaction.get(doctype_field)

				if not docname:
					continue

				doc = frappe.get_doc(doctype, docname)

				# do not try and cancel draft or cancelled documents
				if doc.docstatus != 1:
					continue

				# do not cancel refunded orders
				if doctype == "Sales Invoice" and doc.status in ["Return", "Credit Note Issued"]:
					continue

				# allow cancelling invoices and maintaining links with payout
				doc.ignore_linked_doctypes = ["Shopify Payout"]

				# catch any other errors and log it
				try:
					doc.cancel()
				except Exception as e:
					make_shopify_log(status="Error", exception=e)

				transaction.db_set(doctype_field, None)

	def create_sales_returns(self):
		transactions = [transaction for transaction in self.transactions
			if transaction.sales_invoice and transaction.source_order_id]

		if not transactions:
			return

		for transaction in transactions:
			financial_status = frappe.scrub(transaction.source_order_financial_status)

			if financial_status not in ["refunded", "partially_refunded"]:
				continue

			is_invoice_returned = frappe.db.get_value("Sales Invoice", transaction.sales_invoice, "status") in \
				["Return", "Credit Note Issued"]

			if not is_invoice_returned:
				si_doc = frappe.get_doc("Sales Invoice", transaction.sales_invoice)
				create_sales_return(transaction.source_order_id, financial_status, si_doc)

	def create_payout_journal_entry(self):
		entries = []

		# make payout cash entry
		for transaction in self.transactions:
			if transaction.total_amount and transaction.transaction_type.lower() == "payout":
				account = get_tax_account_head("payout")
				amount = flt(transaction.net_amount)
				entry = get_accounting_entry(account=account, amount=amount)
				entries.append(entry)

		# get the list of transactions that need to be balanced
		payouts_by_invoice = defaultdict(list)
		for transaction in self.transactions:
			if transaction.sales_invoice:
				payouts_by_invoice[transaction.sales_invoice].append(transaction)

		# generate journal entries for each missing transaction
		for invoice, order_transactions in payouts_by_invoice.items():
			party_name = frappe.get_cached_value("Sales Invoice", invoice, "customer")
			account = frappe.get_cached_value("Sales Invoice", invoice, "debit_to")

			for transaction in order_transactions:
				if transaction.net_amount:
					amount = flt(transaction.net_amount)
					entry = get_accounting_entry(
						account=account,
						amount=amount,
						reference_type="Sales Invoice",
						reference_name=invoice,
						party_type="Customer",
						party_name=party_name
					)

					entries.append(entry)

		# only create a JE if any of the payout transactions has been invoiced;
		# the first entry will always be the summary payout entry
		if entries and len(entries) > 1:
			journal_entry = frappe.new_doc("Journal Entry")
			journal_entry.posting_date = frappe.utils.today()
			journal_entry.set("accounts", entries)
			journal_entry.save()
			journal_entry.submit()
