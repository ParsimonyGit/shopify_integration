# -*- coding: utf-8 -*-
# Copyright (c) 2021, Parsimony LLC and Contributors
# See license.txt

import json
import os
import secrets
import unittest

import frappe
from frappe.core.doctype.data_import.data_import import import_doc
from frappe.utils import cstr

from shopify_integration.customers import create_customer
from shopify_integration.orders import sync_sales_order
from shopify_integration.products import make_item
from shopify_integration.utils import get_shopify_document


class ShopifySettings(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")

		# use the fixture data
		import_doc(path=frappe.get_app_path("shopify_integration", "shopify_integration/doctype/shopify_settings/test_data/custom_field.json"),
			ignore_links=True, overwrite=True)

		frappe.reload_doctype("Customer")
		frappe.reload_doctype("Sales Order")
		frappe.reload_doctype("Delivery Note")
		frappe.reload_doctype("Sales Invoice")

		self.setup_shopify()

	def setup_shopify(self):
		shopify_settings = frappe.get_single("Shopify Settings")
		shopify_settings.update({
			"app_type": "Private",
			"shopify_url": "test.myshopify.com",
			"api_key": secrets.token_urlsafe(nbytes=16),
			"password": secrets.token_urlsafe(nbytes=16),
			"shared_secret": secrets.token_urlsafe(nbytes=16),
			"price_list": "_Test Price List",
			"warehouse": "_Test Warehouse - _TC",
			"cash_bank_account": "Cash - _TC",
			"account": "Cash - _TC",
			"customer_group": "_Test Customer Group",
			"cost_center": "Main - _TC",
			"enable_shopify": 0,
			"sales_order_series": "SO-",
			"sync_sales_invoice": 1,
			"sales_invoice_series": "SINV-",
			"sync_delivery_note": 1,
			"delivery_note_series": "DN-",
			"tax_account": "Legal Expenses - _TC",
			"shipping_account": "Legal Expenses - _TC",
			"cash_bank_account": "Legal Expenses - _TC",
			"payment_fee_account": "Legal Expenses - _TC"
		}).save(ignore_permissions=True)

	def test_order(self):
		# create customer
		with open(os.path.join(os.path.dirname(__file__), "test_data", "shopify_customer.json")) as shopify_customer:
			shopify_customer = json.loads(shopify_customer.read())
			create_customer(shopify_customer.get("customer"))

		# create item
		with open(os.path.join(os.path.dirname(__file__), "test_data", "shopify_item.json")) as shopify_item:
			shopify_item = json.loads(shopify_item.read())
			make_item(shopify_item.get("product"))

		# create order
		with open(os.path.join(os.path.dirname(__file__), "test_data", "shopify_order.json")) as shopify_order:
			shopify_order = json.loads(shopify_order.read())
			sync_sales_order(shopify_order.get("order"))

		# verify sales order IDs
		shopify_order_id = cstr(shopify_order.get("order", {}).get("id"))
		sales_order = get_shopify_document("Sales Order", shopify_order_id)
		self.assertEqual(shopify_order_id, sales_order.shopify_order_id)

		# verify customer IDs
		shopify_order_customer_id = cstr(shopify_order.get("order", {}).get("customer", {}).get("id"))
		sales_order_customer_id = frappe.db.get_value("Customer", sales_order.customer, "shopify_customer_id")
		self.assertEqual(shopify_order_customer_id, sales_order_customer_id)

		# verify sales invoice totals
		sales_invoice = get_shopify_document("Sales Invoice", sales_order.shopify_order_id)
		self.assertEqual(sales_invoice.rounded_total, sales_order.rounded_total)

		# verify delivery notes created for all fulfillments
		delivery_note_count = frappe.db.sql("""select count(*) from `tabDelivery Note`
			where shopify_order_id = %s""", sales_order.shopify_order_id)[0][0]

		self.assertEqual(delivery_note_count, len(shopify_order.get("order", {}).get("fulfillments")))
