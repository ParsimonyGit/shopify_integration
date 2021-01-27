# -*- coding: utf-8 -*-
# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import contextlib
from shopify import Session, Webhook

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
		if not self.enable_shopify:
			# a no-op session manager in case Shopify is disabled
			return contextlib.suppress()

		args = (self.shopify_url, self.api_version, self.get_password("password"))
		if temp:
			return Session.temp(*args)
		return Session(*args)

	def validate(self):
		if self.enable_shopify:
			setup_custom_fields()
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
		session = self.get_shopify_session()

		for topic in self.webhook_topics:
			Webhook.activate_session(session)
			if Webhook.find(topic=topic):
				continue

			webhook = Webhook.create({
				"topic": topic,
				"address": get_webhook_address(connector_name="shopify_connection",
					method="store_request_data"),
				"format": "json"
			})

			Webhook.clear_session()

			if webhook.is_valid():
				self.append("webhooks", {
					"webhook_id": webhook.id,
					"method": webhook.topic
				})
			else:
				make_shopify_log(status="Error", response_data=webhook.to_dict(),
					exception=webhook.errors.full_messages(), rollback=True)

	def unregister_webhooks(self):
		session = self.get_shopify_session()

		deleted_webhooks = []
		for d in self.webhooks:
			Webhook.activate_session(session)

			if not Webhook.exists(d.webhook_id):
				deleted_webhooks.append(d)
				continue

			try:
				webhook = Webhook.find(d.webhook_id)
				webhook.destroy()
			except Exception as e:
				make_shopify_log(status="Error", exception=e, rollback=True)
				frappe.log_error(message=e, title="Shopify Webhooks Deletion Issue")
			else:
				deleted_webhooks.append(d)
			finally:
				Webhook.clear_session()

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
