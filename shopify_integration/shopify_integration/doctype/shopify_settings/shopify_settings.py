# -*- coding: utf-8 -*-
# Copyright (c) 2021, Parsimony, LLC and contributors
# For license information, please see license.txt

from typing import TYPE_CHECKING, Optional, Type

from shopify.collection import PaginatedCollection, PaginatedIterator
from shopify.resources import (
	Order,
	Payouts,
	Product,
	Refund,
	Transactions,
	Variant,
	Webhook,
)
from shopify.session import Session as ShopifySession

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import get_default_naming_series
from frappe.utils import get_datetime_str, get_first_day, today

from shopify_integration.shopify_integration.doctype.shopify_log.shopify_log import (
	make_shopify_log,
)

if TYPE_CHECKING:
	from shopify.base import ShopifyResource

	from frappe.integrations.doctype.connected_app.connected_app import ConnectedApp
	from frappe.integrations.doctype.token_cache.token_cache import TokenCache


class ShopifySettings(Document):
	api_version = "2022-07"

	@staticmethod
	@frappe.whitelist()
	def get_series():
		return {
			"sales_order_series": get_default_naming_series("Sales Order")
			or "SO-Shopify-",
			"sales_invoice_series": get_default_naming_series("Sales Invoice")
			or "SI-Shopify-",
			"delivery_note_series": get_default_naming_series("Delivery Note")
			or "DN-Shopify-",
		}

	def validate(self):
		self.update_webhooks()

	def get_shopify_access_token(self):
		from shopify_integration.oauth import DEFAULT_TOKEN_USER

		if self.app_type not in ("Custom (OAuth)", "Public"):
			return

		connected_app: "ConnectedApp" = frappe.get_doc(
			"Connected App", self.connected_app
		)

		token_cache: Optional["TokenCache"] = connected_app.get_token_cache(
			DEFAULT_TOKEN_USER,
		)

		if token_cache:
			return token_cache.get_password("access_token")

	def get_shopify_session(self, temp: bool = False):
		token = None
		# adding "Private" for backwards compatibility
		if self.app_type in ("Custom", "Private"):
			token = self.get_password("password")
		elif self.app_type in ("Custom (OAuth)", "Public"):
			token = self.get_shopify_access_token()

		if not token:
			frappe.throw(_("Shopify access token or password not found"))

		args = (self.shopify_url, self.api_version, token)
		if temp:
			return ShopifySession.temp(*args)
		return ShopifySession(*args)

	def get_resources(self, resource: Type["ShopifyResource"], *args, **kwargs):
		with self.get_shopify_session(temp=True):
			resources = resource.find(*args, **kwargs)

			# if a limited number of documents are requested, don't keep looping;
			# this is a side-effect from the way the library works, since it
			# doesn't process the "limit" keyword
			if "limit" in kwargs:
				return (
					resources
					if isinstance(resources, PaginatedCollection)
					else [resources]
				)

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

		frappe.enqueue(
			method=sync_items_from_shopify,
			queue="long",
			is_async=True,
			**{"shop_name": self.name}
		)

	@frappe.whitelist()
	def sync_payouts(self, start_date: str = str()):
		"Pull and sync payouts from Shopify Payments transactions"
		from shopify_integration.payouts import create_shopify_payouts

		if not start_date:
			start_date = get_datetime_str(get_first_day(today()))
		frappe.enqueue(
			method=create_shopify_payouts,
			queue="long",
			is_async=True,
			**{"shop_name": self.name, "start_date": start_date}
		)

	def update_webhooks(self):
		if frappe.conf.developer_mode:
			return

		if (
			self.app_type in ("Custom (OAuth)", "Public")
			and not self.get_shopify_access_token()
		):
			return

		if self.enable_shopify and not self.webhooks:
			self.register_webhooks()
		elif not self.enable_shopify:
			self.unregister_webhooks()

	def register_webhooks(self):
		from shopify_integration.webhooks import (
			get_webhook_url,
			SHOPIFY_WEBHOOK_TOPIC_MAPPER,
		)

		for topic in SHOPIFY_WEBHOOK_TOPIC_MAPPER:
			with self.get_shopify_session(temp=True):
				webhook = Webhook.create(
					{"topic": topic, "address": get_webhook_url(), "format": "json"}
				)

			if webhook.is_valid():
				self.append(
					"webhooks", {"webhook_id": webhook.id, "method": webhook.topic}
				)
			else:
				make_shopify_log(
					shop_name=self.name,
					status="Error",
					response_data=webhook.to_dict(),
					exception=webhook.errors.full_messages(),
					rollback=True,
				)

	def unregister_webhooks(self):
		deleted_webhooks = []
		for webhook in self.webhooks:
			with self.get_shopify_session(temp=True):
				if not Webhook.exists(webhook.webhook_id):
					deleted_webhooks.append(webhook)
					continue

			try:
				existing_webhooks = self.get_webhooks(webhook.webhook_id)
			except Exception as e:
				make_shopify_log(
					shop_name=self.name, status="Error", exception=e, rollback=True
				)
				continue

			for existing_webhook in existing_webhooks:
				try:
					existing_webhook.destroy()
				except Exception as e:
					make_shopify_log(
						shop_name=self.name, status="Error", exception=e, rollback=True
					)
				else:
					deleted_webhooks.append(webhook)

		for webhook in deleted_webhooks:
			self.remove(webhook)
