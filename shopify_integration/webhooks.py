import base64
import hashlib
import hmac
import json

import frappe
from frappe import _

SHOPIFY_WEBHOOK_TOPIC_MAPPER = {
	"orders/create": "shopify_integration.orders.create_shopify_documents",
	"orders/paid": "shopify_integration.invoices.prepare_sales_invoice",
	"orders/fulfilled": "shopify_integration.fulfilments.prepare_delivery_note",
	"orders/cancelled": "shopify_integration.orders.cancel_shopify_order"
}


@frappe.whitelist(allow_guest=True)
def store_request_data():
	if not frappe.request:
		return

	event = frappe.request.headers.get("X-Shopify-Topic")
	if not SHOPIFY_WEBHOOK_TOPIC_MAPPER.get(event):
		return

	shop_name = get_shop_for_webhook()
	if shop_name:
		validate_webhooks_request(
			doctype="Shopify Settings",
			name=shop_name,
			hmac_key="X-Shopify-Hmac-Sha256",
			secret_key="shared_secret",
		)

		data = json.loads(frappe.request.data)
		dump_request_data(shop_name, data, event)


def validate_webhooks_request(doctype, name, hmac_key, secret_key="secret"):
	if not frappe.request or frappe.flags.in_test:
		return

	shop = frappe.get_doc(doctype, name)
	if shop and shop.get(secret_key):
		digest = hmac.new(
			key=shop.get(secret_key).encode("utf8"),
			msg=frappe.request.data,
			digestmod=hashlib.sha256,
		).digest()
		computed_hmac = base64.b64encode(digest)

		if (
			frappe.request.data
			and frappe.get_request_header(hmac_key)
			and computed_hmac != bytes(frappe.get_request_header(hmac_key).encode())
		):
			frappe.throw(_("Unverified Shopify Webhook Data"))


def dump_request_data(shop_name, data, event="orders/create"):
	frappe.set_user("Administrator")
	log = frappe.get_doc({
		"doctype": "Shopify Log",
		"request_data": json.dumps(data, indent=1),
		"method": SHOPIFY_WEBHOOK_TOPIC_MAPPER.get(event),
	}).insert(ignore_permissions=True)

	frappe.db.commit()
	frappe.enqueue(
		method=SHOPIFY_WEBHOOK_TOPIC_MAPPER.get(event),
		queue="short",
		timeout=300,
		is_async=True,
		**{"shop": shop_name, "order": data, "log_id": log.name}
	)


def get_shop_for_webhook():
	shop_domain = frappe.request.headers.get("X-Shopify-Shop-Domain")

	active_shops = frappe.get_all("Shopify Settings",
		filters={"enable_shopify": True},
		fields=["name", "shopify_url"]
	)

	for active_shop in active_shops:
		# sometimes URLs can include HTTP schemes, so only check if
		# the domain is in the Shopify URL
		if shop_domain in active_shop.shopify_url:
			return active_shop.name


def get_webhook_url():
	# Shopify only supports HTTPS requests
	return f"https://{frappe.request.host}/api/method/shopify_integration.webhooks.store_request_data"
