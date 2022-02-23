import binascii
import json
import os
from typing import TYPE_CHECKING, Dict, List, Optional, Union

from shopify.session import Session as ShopifySession
from shopify.utils.shop_url import sanitize_shop_domain

import frappe
from frappe import _

if TYPE_CHECKING:
	from frappe.integrations.doctype.connected_app.connected_app import ConnectedApp
	from frappe.integrations.doctype.token_cache.token_cache import TokenCache
	from shopify_integration.shopify_integration.doctype.shopify_settings.shopify_settings import (
		ShopifySettings,
	)


@frappe.whitelist()
def install_custom_app(*args, **kwargs):
	# validate shop URL in response
	shop_url = sanitize_shop_domain(kwargs.get("shop"))
	if not shop_url:
		frappe.throw(_("Invalid shop URL"))

	shops: List["ShopifySettings"] = frappe.get_all(
		"Shopify Settings",
		filters={
			"enable_shopify": True,
			"shopify_url": ["LIKE", f"%{kwargs.get('shop')}%"],
		},
		fields=["name", "connected_app"],
	)

	if not shops:
		frappe.throw(_(f"No Shopify Settings found for {kwargs.get('shop')}"))

	shopify_settings = shops[0]

	# remove Frappe's argument to properly validate HMAC
	kwargs.pop("cmd")

	auth_url = initiate_web_application_flow(shopify_settings)
	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = auth_url


@frappe.whitelist()
def initiate_web_application_flow(settings: Union["ShopifySettings", str]):
	"""Return an authorization URL for the user, and save the state in Token Cache."""

	if isinstance(settings, str):
		settings: Dict = json.loads(settings)

	shopify_settings: "ShopifySettings" = frappe.get_doc(
		"Shopify Settings", settings.get("name")
	)
	connected_app: "ConnectedApp" = frappe.get_doc(
		"Connected App", settings.get("connected_app")
	)

	ShopifySession.setup(
		api_key=connected_app.client_id,
		secret=connected_app.get_password("client_secret"),
	)

	state = binascii.b2a_hex(os.urandom(15)).decode("utf-8")
	shopify_session = ShopifySession(
		shopify_settings.shopify_url, shopify_settings.api_version
	)
	auth_url = shopify_session.create_permission_url(
		connected_app.get_scopes(), connected_app.redirect_uri, state
	)

	# create an initial token cache for the user
	token_cache = connected_app.get_token_cache(frappe.session.user)
	if not token_cache:
		token_cache = frappe.new_doc("Token Cache")
		token_cache.user = frappe.session.user
		token_cache.connected_app = connected_app.name
	token_cache.state = state
	token_cache.save(ignore_permissions=True)

	return auth_url


@frappe.whitelist(allow_guest=True)
def callback(*args, **kwargs):
	validate_request(*args, **kwargs)
	connected_app, token_cache = get_oauth_details(*args, **kwargs)
	shopify_settings = get_shopify_settings(connected_app)

	if not shopify_settings:
		frappe.throw(_(f"No Shopify Settings found for {kwargs.get('shop')}"))

	# remove Frappe's argument to properly validate HMAC
	kwargs.pop("cmd")

	session = ShopifySession(shopify_settings.shopify_url, shopify_settings.api_version)
	access_token = session.request_token(kwargs)
	token_cache = token_cache.update_data(
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
	# validate request method
	if frappe.request.method != "GET":
		frappe.throw(_("Invalid request method: {}").format(frappe.request.method))

	# validate redirect URI parameters; check if connected app is available
	# example request path: "/api/method/path.to.method/connected_app_name"
	path = frappe.request.path[1:].split("/")
	if len(path) != 4 or not path[3]:
		frappe.throw(_("Invalid parameters"))

	# validate shop URL in response
	shop_url = sanitize_shop_domain(kwargs.get("shop"))
	if not shop_url:
		frappe.throw(_("Invalid shop URL"))


def get_oauth_details(*args, **kwargs):
	# check if connected app is available; example request path:
	# "/api/method/path.to.method/connected_app_name"
	path = frappe.request.path[1:].split("/")

	connected_app: "ConnectedApp" = frappe.get_doc("Connected App", path[3])
	token_cache: "TokenCache" = connected_app.get_token_cache(frappe.session.user)
	if not token_cache:
		token_cache = frappe.new_doc("Token Cache")
		token_cache.user = frappe.session.user
		token_cache.connected_app = connected_app.name
		token_cache.state = kwargs.get("state")
		token_cache.save(ignore_permissions=True)

	# compare token cache states
	if kwargs.get("state") != token_cache.state:
		frappe.throw(_("Invalid state"))

	return connected_app, token_cache


def get_shopify_settings(connected_app: "ConnectedApp") -> Optional["ShopifySettings"]:
	shopify_settings: List["ShopifySettings"] = frappe.get_all(
		"Shopify Settings",
		filters={
			"enable_shopify": True,
			"connected_app": connected_app.name,
		},
	)

	if not shopify_settings:
		return

	return frappe.get_doc("Shopify Settings", shopify_settings[0].name)
