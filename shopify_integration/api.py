from typing import TYPE_CHECKING

from shopify.session import Session as ShopifySession
from shopify.utils.shop_url import sanitize_shop_domain

import frappe
from frappe import _

from shopify_integration.hook_events.connected_app import API_VERSION, SHOP_URL

if TYPE_CHECKING:
	from frappe.integrations.doctype.connected_app.connected_app import ConnectedApp
	from frappe.integrations.doctype.token_cache.token_cache import TokenCache


@frappe.whitelist(allow_guest=True)
def callback(*args, **kwargs):
	connected_app, token_cache = validate_request(*args, **kwargs)

	# remove Frappe's argument to properly validate HMAC
	kwargs.pop("cmd")

	session = ShopifySession(SHOP_URL, API_VERSION)
	access_token = session.request_token(kwargs)
	token_cache.update_data(
		{
			"token_type": "Bearer",
			"access_token": access_token,
		}
	)

	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = (
		token_cache.get("success_uri") or connected_app.get_url()
	)


def validate_request(*args, **kwargs):
	"""Validate request and return connected app and token cache."""

	# validate request method
	if frappe.request.method != "GET":
		frappe.throw(_("Invalid request method: {}").format(frappe.request.method))

	# validate redirect URI parameters
	path = frappe.request.path[1:].split("/")
	if len(path) != 4 or not path[3]:
		frappe.throw(_("Invalid parameters"))

	# validate shop URL in response
	shop_url = sanitize_shop_domain(kwargs.get("shop"))
	if not shop_url:
		frappe.throw(_("Invalid shop URL"))

	# compare token cache states
	connected_app: "ConnectedApp" = frappe.get_doc("Connected App", path[3])
	token_cache: "TokenCache" = connected_app.get_token_cache(frappe.session.user)
	if not token_cache:
		token_cache = frappe.new_doc("Token Cache")
		token_cache.user = frappe.session.user
		token_cache.connected_app = connected_app.name
		token_cache.state = kwargs.get("state")
		token_cache.save(ignore_permissions=True)

	if kwargs.get("state") != token_cache.state:
		frappe.throw(_("Invalid state"))

	return connected_app, token_cache
