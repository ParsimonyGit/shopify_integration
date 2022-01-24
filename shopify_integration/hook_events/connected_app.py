import binascii
import os

from shopify.session import Session as ShopifySession

import frappe
from frappe.integrations.doctype.connected_app.connected_app import ConnectedApp

SHOP_URL = "parsimony-public-app-test.myshopify.com"
API_VERSION = "2022-01"


class ShopifyConnectedApp(ConnectedApp):
	@frappe.whitelist()
	def initiate_web_application_flow(self, user=None, success_uri=None):
		"""Return an authorization URL for the user. Save state in Token Cache."""
		ShopifySession.setup(
			api_key=self.client_id,
			secret=self.get_password("client_secret"),
		)

		state = binascii.b2a_hex(os.urandom(15)).decode("utf-8")
		shopify_session = ShopifySession(SHOP_URL, API_VERSION)
		auth_url = shopify_session.create_permission_url(
			self.get_scopes(), self.redirect_uri, state
		)

		# create an initial token cache for the user
		user = user or frappe.session.user
		token_cache = self.get_token_cache(user)
		if not token_cache:
			token_cache = frappe.new_doc("Token Cache")
			token_cache.user = user
			token_cache.connected_app = self.name
		token_cache.success_uri = success_uri
		token_cache.state = state
		token_cache.save(ignore_permissions=True)

		return auth_url
