from typing import TYPE_CHECKING
from urllib.parse import urljoin

import frappe

if TYPE_CHECKING:
	from frappe.integrations.doctype.connected_app.connected_app import ConnectedApp


def validate_redirect_uri(connected_app: "ConnectedApp", method: str):
	if "shopify" in connected_app.provider_name.lower():
		base_url = frappe.utils.get_url()
		callback_path = (
			"/api/method/shopify_integration.oauth.callback/" + connected_app.name
		)
		connected_app.redirect_uri = urljoin(base_url, callback_path)
