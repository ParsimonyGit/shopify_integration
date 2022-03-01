import base64
import hashlib
import hmac
import json
from typing import TYPE_CHECKING, Dict, List, Optional

from shopify import Order

import frappe
from frappe import _

if TYPE_CHECKING:
	from frappe.integrations.doctype.connected_app.connected_app import ConnectedApp
	from shopify_integration.shopify_integration.doctype.shopify_log.shopify_log import (
		ShopifyLog,
	)
	from shopify_integration.shopify_integration.doctype.shopify_settings.shopify_settings import (
		ShopifySettings,
	)

SHOPIFY_WEBHOOK_TOPIC_MAPPER = {
	"orders/create": "shopify_integration.orders.create_shopify_documents",
	"orders/paid": "shopify_integration.invoices.prepare_sales_invoice",
	"orders/fulfilled": "shopify_integration.fulfilments.prepare_delivery_note",
	"orders/cancelled": "shopify_integration.orders.cancel_shopify_order",
}


@frappe.whitelist(allow_guest=True)
def store_request_data():
	if not frappe.request:
		return

	event: str = frappe.request.headers.get("X-Shopify-Topic")
	if not SHOPIFY_WEBHOOK_TOPIC_MAPPER.get(event):
		return

	shop_name = get_shop_for_webhook()
	if not shop_name:
		return

	shop: "ShopifySettings" = frappe.get_doc("Shopify Settings", shop_name)
	validate_webhooks_request(
		shop=shop,
		hmac_key="X-Shopify-Hmac-SHA256",
	)

	data: Dict = json.loads(frappe.request.data)
	enqueue_webhook_event(shop_name, data, event)


def validate_webhooks_request(shop: "ShopifySettings", hmac_key: str):
	if frappe.flags.in_test:
		return

	key = None
	if shop.app_type == "Custom":
		key = shop.shared_secret.encode("utf8")
	elif shop.app_type in ("Custom (OAuth)", "Public"):
		connected_app: "ConnectedApp" = frappe.get_doc(
			"Connected App", shop.connected_app
		)
		key = connected_app.get_password("client_secret").encode("utf8")

	if not key:
		frappe.throw(_("Missing secret to validate webhook request"))

	digest = hmac.new(
		key=key,
		msg=frappe.request.data,
		digestmod=hashlib.sha256,
	).digest()
	computed_hmac = base64.b64encode(digest)

	hmac_key = frappe.get_request_header(hmac_key)
	if not hmac.compare_digest(computed_hmac, hmac_key.encode('utf-8')):
		frappe.throw(_("Unverified Shopify Webhook data"))


def enqueue_webhook_event(shop_name: str, data: Dict, event: str = "orders/create"):
	frappe.set_user("Administrator")
	log = create_shopify_log(shop_name, data, event)
	order = Order()
	order.attributes.update(data)
	frappe.enqueue(
		method=SHOPIFY_WEBHOOK_TOPIC_MAPPER.get(event),
		queue="short",
		timeout=300,
		is_async=True,
		**{"shop_name": shop_name, "order": order, "log_id": log.name},
	)


def create_shopify_log(shop_name: str, data: Dict, event: str = "orders/create"):
	log: "ShopifyLog" = frappe.get_doc(
		{
			"doctype": "Shopify Log",
			"shop": shop_name,
			"request_data": json.dumps(data, indent=1),
			"method": SHOPIFY_WEBHOOK_TOPIC_MAPPER.get(event),
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return log


def get_shop_for_webhook() -> Optional[str]:
	active_shops: List["ShopifySettings"] = frappe.get_all(
		"Shopify Settings",
		filters={"enable_shopify": True},
		fields=["name", "shopify_url"],
	)

	shop_domain: str = frappe.request.headers.get("X-Shopify-Shop-Domain")
	for active_shop in active_shops:
		# sometimes URLs can include HTTP schemes, so only check if
		# the domain is in the Shopify URL
		if shop_domain in active_shop.shopify_url:
			return active_shop.name


def get_webhook_url():
	# Shopify only supports HTTPS requests
	return f"https://{frappe.request.host}/api/method/shopify_integration.webhooks.store_request_data"
