# -*- coding: utf-8 -*-
# Copyright (c) 2021, Parsimony LLC and Contributors
# See license.txt

import json
import os
import secrets
import unittest

from shopify import (
	Address,
	Customer,
	Fulfillment,
	Image,
	LineItem,
	Order,
	Product,
	ShippingLine,
)

import frappe
from frappe.core.doctype.data_import.data_import import import_doc
from frappe.utils import cstr

from shopify_integration.customers import create_customer
from shopify_integration.fulfilments import create_shopify_delivery
from shopify_integration.invoices import create_shopify_invoice
from shopify_integration.orders import create_sales_order
from shopify_integration.products import make_item
from shopify_integration.utils import get_shopify_document


class ShopifySettings(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")

		# use the fixture data
		import_doc(
			frappe.get_app_path(
				"shopify_integration",
				"shopify_integration/doctype/shopify_settings/test_data/custom_field.json",
			)
		)

		frappe.reload_doctype("Customer")
		frappe.reload_doctype("Sales Order")
		frappe.reload_doctype("Delivery Note")
		frappe.reload_doctype("Sales Invoice")

		setup_shopify()

	def test_order(self):
		shopify_settings = frappe.get_doc("Shopify Settings", "Test Shopify")

		# create customer
		with open(
			os.path.join(
				os.path.dirname(__file__), "test_data", "shopify_customer.json"
			)
		) as shopify_customer:
			customer = Customer()
			customer_data = json.loads(shopify_customer.read())
			formatted_customer_data = prepare_customer_format(customer_data)
			customer.attributes.update(formatted_customer_data)
			create_customer(shopify_settings.name, customer)

		# create item
		with open(
			os.path.join(os.path.dirname(__file__), "test_data", "shopify_item.json")
		) as shopify_item:
			item = Product()
			product_data = json.loads(shopify_item.read())
			formatted_product_data = prepare_product_format(product_data)
			item.attributes.update(formatted_product_data)
			make_item(shopify_settings, item)

		# create order, invoice and delivery
		with open(
			os.path.join(os.path.dirname(__file__), "test_data", "shopify_order.json")
		) as shopify_order:
			order = Order()
			order_data = json.loads(shopify_order.read())
			formatted_order_data = prepare_order_format(order_data)
			order.attributes.update(formatted_order_data)

			sales_order = create_sales_order(shopify_settings.name, order)
			create_shopify_invoice(shopify_settings.name, order, sales_order)
			create_shopify_delivery(shopify_settings.name, order, sales_order)

		# verify sales order IDs
		sales_order = get_shopify_document(
			shopify_settings.name, "Sales Order", order_id=order.id
		)
		self.assertEqual(cstr(order.id), sales_order.shopify_order_id)

		# verify customer IDs
		shopify_order_customer_id = cstr(order.customer.id)
		sales_order_customer_id = frappe.db.get_value(
			"Customer", sales_order.customer, "shopify_customer_id"
		)
		self.assertEqual(shopify_order_customer_id, sales_order_customer_id)

		# verify sales invoice totals
		sales_invoice = get_shopify_document(
			shopify_settings.name,
			"Sales Invoice",
			order_id=sales_order.shopify_order_id,
		)
		self.assertEqual(sales_invoice.rounded_total, sales_order.rounded_total)

		# verify delivery notes created for all fulfillments
		delivery_note = get_shopify_document(
			shopify_settings.name,
			"Delivery Note",
			order_id=sales_order.shopify_order_id,
		)
		self.assertEqual(len(delivery_note.items), len(order.fulfillments))


def prepare_customer_format(customer_data):
	# simulate the Shopify customer object with proper class instances
	if "addresses" in customer_data:
		customer_addresses = []
		for address in customer_data.get("addresses"):
			customer_address = Address()
			customer_address.attributes.update(address)
			customer_addresses.append(customer_address)
		customer_data.update({"addresses": customer_addresses})
	return customer_data


def prepare_product_format(product_data):
	# simulate the Shopify product object with proper class instances
	if "image" in product_data:
		product_image = Image()
		product_image.attributes.update(product_data.get("image"))
		product_data.update({"image": product_image})
	return product_data


def prepare_order_format(order_data):
	# simulate the Shopify order object with proper class instances
	if "customer" in order_data:
		order_customer = Customer()
		order_customer.attributes.update(order_data.get("customer"))
		order_data.update({"customer": order_customer})
	if "line_items" in order_data:
		order_line_items = []
		for line_item in order_data.get("line_items"):
			order_line_item = LineItem()
			order_line_item.attributes.update(line_item)
			order_line_items.append(order_line_item)
		order_data.update({"line_items": order_line_items})
	if "shipping_lines" in order_data:
		order_shipping_lines = []
		for shipping_line in order_data.get("shipping_lines"):
			order_shipping_line = ShippingLine()
			order_shipping_line.attributes.update(shipping_line)
			order_shipping_lines.append(order_shipping_line)
		order_data.update({"shipping_lines": order_shipping_lines})
	if "fulfillments" in order_data:
		order_fulfillments = []
		for fulfillment in order_data.get("fulfillments"):
			if "line_items" in fulfillment:
				fulfillment_line_items = []
				for line_item in fulfillment.get("line_items"):
					fulfillment_line_item = LineItem()
					fulfillment_line_item.attributes.update(line_item)
					fulfillment_line_items.append(fulfillment_line_item)
				fulfillment.update({"line_items": fulfillment_line_items})
			order_fulfillment = Fulfillment()
			order_fulfillment.attributes.update(fulfillment)
			order_fulfillments.append(order_fulfillment)
		order_data.update({"fulfillments": order_fulfillments})

	return order_data


def setup_shopify():
	if frappe.db.exists("Shopify Settings", "Test Shopify"):
		return

	shopify_settings = frappe.new_doc("Shopify Settings")
	shopify_settings.update(
		{
			"app_type": "Custom",
			"shop_name": "Test Shopify",
			"shopify_url": "test.myshopify.com",
			"company": "_Test Company",
			"api_key": secrets.token_urlsafe(nbytes=16),
			"password": secrets.token_urlsafe(nbytes=16),
			"shared_secret": secrets.token_urlsafe(nbytes=16),
			"price_list": "_Test Price List",
			"warehouse": "_Test Warehouse - _TC",
			"account": "Cash - _TC",
			"customer_group": "_Test Customer Group",
			"cost_center": "Main - _TC",
			"item_group": "_Test Item Group",
			"enable_shopify": 0,
			"sales_order_series": "SO-",
			"sync_sales_invoice": 1,
			"sales_invoice_series": "SINV-",
			"sync_delivery_note": 1,
			"delivery_note_series": "DN-",
			"cash_bank_account": "Cash - _TC",
			"tax_account": "Legal Expenses - _TC",
			"shipping_account": "Legal Expenses - _TC",
			"payment_fee_account": "Legal Expenses - _TC",
		}
	).save(ignore_permissions=True)
