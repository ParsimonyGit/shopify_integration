# -*- coding: utf-8 -*-
# Copyright (c) 2021, Parsimony, LLC and contributors
# For license information, please see license.txt

from shopify.collection import PaginatedCollection, PaginatedIterator
from shopify.resources import Order, Payouts, Product, Refund, Transactions, Variant, Webhook
from shopify.session import Session as ShopifySession

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime_str, get_first_day, today

from shopify_integration.shopify_integration.doctype.shopify_log.shopify_log import make_shopify_log


class ShopifySettings(Document):
	api_version = "2022-04"

	@staticmethod
	@frappe.whitelist()
	def get_series():
		return {
			"sales_order_series": frappe.get_meta("Sales Order").get_options("naming_series") or "SO-Shopify-",
			"sales_invoice_series": frappe.get_meta("Sales Invoice").get_options("naming_series") or "SI-Shopify-",
			"delivery_note_series": frappe.get_meta("Delivery Note").get_options("naming_series") or "DN-Shopify-"
		}

	def validate(self):
		if self.enable_shopify:
			self.validate_access_credentials()

		if not frappe.conf.developer_mode:
			self.update_webhooks()

	def get_shopify_session(self, temp=False):
		args = (self.shopify_url, self.api_version, self.get_password("password"))
		if temp:
			return ShopifySession.temp(*args)
		return ShopifySession(*args)

	def get_resources(self, resource, *args, **kwargs):
		with self.get_shopify_session(temp=True):
			resources = resource.find(*args, **kwargs)

			# if a limited number of documents are requested, don't keep looping;
			# this is a side-effect from the way the library works, since it
			# doesn't process the "limit" keyword
			if "limit" in kwargs:
				return resources if isinstance(resources, PaginatedCollection) else [resources]

			if isinstance(resources, PaginatedCollection):
				# Shopify's API limits responses to 50 per page by default;
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

	def get_variants(self, *args, **kwargs):
		return self.get_resources(Variant, *args, **kwargs)

	def get_webhooks(self, *args, **kwargs):
		return self.get_resources(Webhook, *args, **kwargs)

	@frappe.whitelist()
	def sync_products(self):
		"Pull and sync products from Shopify, including variants"
		from shopify_integration.products import sync_items_from_shopify
		frappe.enqueue(method=sync_items_from_shopify, queue="long", is_async=True, **{"shop_name": self.name})

	@frappe.whitelist()
	def sync_payouts(self, start_date: str = str()):
		"Pull and sync payouts from Shopify Payments transactions"
		from shopify_integration.payouts import create_shopify_payouts
		if not start_date:
			start_date = get_datetime_str(get_first_day(today()))
		frappe.enqueue(method=create_shopify_payouts, queue='long', is_async=True, **{
			"shop_name": self.name,
			"start_date": start_date
		})

	def validate_access_credentials(self):
		if not self.shopify_url:
			frappe.throw(_("Missing value for Shop URL"))

		if not self.get_password("password", raise_exception=False):
			frappe.throw(_("Missing value for Password"))

	def update_webhooks(self):
		if self.enable_shopify and not self.webhooks:
			self.register_webhooks()
		elif not self.enable_shopify:
			self.unregister_webhooks()

	def register_webhooks(self):
		from shopify_integration.webhooks import get_webhook_url, SHOPIFY_WEBHOOK_TOPIC_MAPPER

		for topic in SHOPIFY_WEBHOOK_TOPIC_MAPPER:
			with self.get_shopify_session(temp=True):
				webhook = Webhook.create({
					"topic": topic,
					"address": get_webhook_url(),
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
