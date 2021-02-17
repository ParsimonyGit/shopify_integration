import json

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
def store_request_data(data=None, event=None):
	if frappe.request:
		data = json.loads(frappe.request.data)
		event = frappe.request.headers.get('X-Shopify-Topic')

	dump_request_data(data, event)


def dump_request_data(data, event="orders/create"):
	event_mapper = {
		"orders/create": "shopify_integration.orders.create_shopify_documents",
		"orders/paid": "shopify_integration.invoices.prepare_sales_invoice",
		"orders/fulfilled": "shopify_integration.fulfilments.prepare_delivery_note",
		"orders/cancelled": "shopify_integration.orders.cancel_shopify_order",
	}

	log = frappe.get_doc({
		"doctype": "Shopify Log",
		"request_data": json.dumps(data, indent=1),
		"method": event_mapper.get(event)
	}).insert(ignore_permissions=True)

	frappe.db.commit()
	frappe.enqueue(method=event_mapper[event], queue='short', timeout=300, is_async=True,
		**{"order": data, "request_id": log.name})


def get_webhook_url():
	# Shopify only supports HTTPS requests
	return f'https://{frappe.request.host}/api/method/shopify_integration.webhooks.store_request_data'
