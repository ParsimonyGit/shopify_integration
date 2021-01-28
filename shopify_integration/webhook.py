import json
from urllib.parse import urlparse

import frappe
from erpnext.erpnext_integrations.utils import validate_webhooks_request

SHOPIFY_WEBHOOK_TOPICS = [
	"orders/create",
	"orders/paid",
	"orders/fulfilled",
	"orders/cancelled"
]


@frappe.whitelist(allow_guest=True)
@validate_webhooks_request("Shopify Settings", 'X-Shopify-Hmac-Sha256', secret_key='shared_secret')
def store_request_data(order=None, event=None):
	if frappe.request:
		order = json.loads(frappe.request.data)
		event = frappe.request.headers.get('X-Shopify-Topic')

	dump_request_data(order, event)


def dump_request_data(data, event="orders/create"):
	event_mapper = {
		"orders/create": get_webhook_address(prefix="connector", method="sync_sales_order", exclude_uri=True),
		"orders/paid": get_webhook_address(prefix="connector", method="prepare_sales_invoice", exclude_uri=True),
		"orders/fulfilled": get_webhook_address(prefix="connector", method="prepare_delivery_note", exclude_uri=True),
		"orders/cancelled": get_webhook_address(prefix="connector", method="cancel_shopify_order", exclude_uri=True)
	}

	log = frappe.get_doc({
		"doctype": "Shopify Log",
		"request_data": json.dumps(data, indent=1),
		"method": event_mapper.get(event)
	}).insert(ignore_permissions=True)

	frappe.db.commit()
	frappe.enqueue(method=event_mapper[event], queue='short', timeout=300, is_async=True,
		**{"order": data, "request_id": log.name})


def get_webhook_address(prefix, method, exclude_uri=False):
	endpoint = f"shopify_integration.webhook.{prefix}.{method}"

	if exclude_uri:
		return endpoint

	try:
		url = frappe.request.url
	except RuntimeError:
		url = "http://localhost:8000"

	uri = urlparse(url)
	server_url = f'{uri.scheme}://{uri.netloc}/api/method/{endpoint}'

	return server_url
