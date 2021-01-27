# -*- coding: utf-8 -*-
# Copyright (c) 2021, Parsimony, LLC and contributors
# For license information, please see license.txt

from shopify.collection import PaginatedCollection, PaginatedIterator
from shopify.resources import Order, Payouts, Product, Refund, Transactions, Webhook
from shopify.session import Session as ShopifySession

import frappe
from erpnext.erpnext_integrations.utils import get_webhook_address
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.model.document import Document
from shopify_integration.shopify_integration.doctype.shopify_log.shopify_log import make_shopify_log


class ShopifySettings(Document):
	api_version = "2021-01"
	webhook_topics = ["orders/create", "orders/paid",
		"orders/fulfilled", "orders/cancelled"]

	def get_shopify_session(self, temp=False):
		args = (self.shopify_url, self.api_version, self.get_password("password"))
		if temp:
			return ShopifySession.temp(*args)
		return ShopifySession(*args)

	def get_resources(self, resource, *args, **kwargs):
		# TODO: figure out a way to nicely handle limits;
		# currently, shopify's PaginatedIterator ignores limits during retrieval

		with self.get_shopify_session(temp=True):
			resources = resource.find(*args, **kwargs)

			if isinstance(resources, PaginatedCollection):
				# Shopify's API limits responses to 50 per page;
				# we keep calling to retrieve all the resource documents
				paged_resources = PaginatedIterator(resources)
				return [resource for page in paged_resources for resource in page]

			# Shopify's API returns instance objects instead of collections
			# for single-result responses
			return [resources]

	def get_orders(self, *args, **kwargs):
		return self.get_resources(Order, *args, **kwargs)

	def get_payouts(self, *args, **kwargs):
		return self.get_resources(Payouts, *args, **kwargs)

	def get_payout_transactions(self, *args, **kwargs):
		return self.get_resources(Transactions, *args, **kwargs)

	def get_products(self, *args, **kwargs):
		return self.get_resources(Product, *args, **kwargs)

	def get_refunds(self, *args, **kwargs):
		return self.get_resources(Refund, *args, **kwargs)

	def get_webhooks(self, *args, **kwargs):
		return self.get_resources(Webhook, *args, **kwargs)

	def validate(self):
		if self.enable_shopify:
			setup_custom_fields()  # TODO: move setup to after install?
			self.validate_access_credentials()

		if not frappe.conf.developer_mode:
			self.update_webhooks()

	def validate_access_credentials(self):
		if not self.shopify_url:
			frappe.throw(_("Missing value for Shop URL"))

		if not self.get_password("password", raise_exception=False):
			frappe.throw(_("Missing value for Password"))

	def update_webhooks(self):
		if self.enable_shopify:
			self.register_webhooks()
		else:
			self.unregister_webhooks()

	def register_webhooks(self):
		for topic in self.webhook_topics:
			if self.get_webhooks(topic=topic):
				continue

			with self.get_shopify_session(temp=True):
				webhook = Webhook.create({
					"topic": topic,
					"address": get_webhook_address(connector_name="shopify_connection",
						method="store_request_data"),
					"format": "json"
				})

			if webhook.is_valid():
				self.append("webhooks", {
					"webhook_id": webhook.id,
					"method": webhook.topic
				})
			else:
				make_shopify_log(status="Error", response_data=webhook.to_dict(),
					exception=webhook.errors.full_messages(), rollback=True)

	def unregister_webhooks(self):
		deleted_webhooks = []
		for d in self.webhooks:
			with self.get_shopify_session(temp=True):
				if not Webhook.exists(d.webhook_id):
					deleted_webhooks.append(d)
					continue

			try:
				existing_webhooks = self.get_webhooks(d.webhook_id)
			except Exception as e:
				make_shopify_log(status="Error", exception=e, rollback=True)
				continue

			for webhook in existing_webhooks:
				try:
					webhook.destroy()
				except Exception as e:
					make_shopify_log(status="Error", exception=e, rollback=True)
				else:
					deleted_webhooks.append(d)

		for d in deleted_webhooks:
			self.remove(d)


@frappe.whitelist()
def get_series():
	return {
		"sales_order_series": frappe.get_meta("Sales Order").get_options("naming_series") or "SO-Shopify-",
		"sales_invoice_series": frappe.get_meta("Sales Invoice").get_options("naming_series") or "SI-Shopify-",
		"delivery_note_series": frappe.get_meta("Delivery Note").get_options("naming_series") or "DN-Shopify-"
	}


def setup_custom_fields():
	custom_fields = {
		"Customer": [
			dict(fieldname='shopify_customer_id', label='Shopify Customer Id',
				fieldtype='Data', insert_after='series', read_only=1, print_hide=1)
		],
		"Supplier": [
			dict(fieldname='shopify_supplier_id', label='Shopify Supplier Id',
				fieldtype='Data', insert_after='supplier_name', read_only=1, print_hide=1)
		],
		"Address": [
			dict(fieldname='shopify_address_id', label='Shopify Address Id',
				fieldtype='Data', insert_after='fax', read_only=1, print_hide=1)
		],
		"Item": [
			dict(fieldname='shopify_variant_id', label='Shopify Variant Id',
				fieldtype='Data', insert_after='item_code', read_only=1, print_hide=1),
			dict(fieldname='shopify_product_id', label='Shopify Product Id',
				fieldtype='Data', insert_after='item_code', read_only=1, print_hide=1),
			dict(fieldname='shopify_description', label='Shopify Description',
				fieldtype='Text Editor', insert_after='description', read_only=1, print_hide=1),
			dict(fieldname='disabled_on_shopify', label='Disabled on Shopify',
				fieldtype='Check', insert_after='disabled', read_only=1, print_hide=1)
		],
		"Sales Order": [
			dict(fieldname='shopify_order_id', label='Shopify Order Id',
				fieldtype='Data', insert_after='title', read_only=1, print_hide=1)
		],
		"Delivery Note": [
			dict(fieldname='shopify_order_id', label='Shopify Order Id',
				fieldtype='Data', insert_after='title', read_only=1, print_hide=1),
			dict(fieldname='shopify_fulfillment_id', label='Shopify Fulfillment Id',
				fieldtype='Data', insert_after='title', read_only=1, print_hide=1)
		],
		"Sales Invoice": [
			dict(fieldname='shopify_order_id', label='Shopify Order Id',
				fieldtype='Data', insert_after='title', read_only=1, print_hide=1)
		]
	}

	create_custom_fields(custom_fields)
