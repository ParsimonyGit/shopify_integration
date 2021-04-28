from urllib.parse import urlparse

import frappe
from frappe.utils.nestedset import get_root_of

from shopify_integration.setup import setup_custom_fields


def execute():
	# store data from original single document
	shopify_settings = frappe.get_doc("Shopify Settings")
	shopify_data = shopify_settings.as_dict(no_default_fields=True)
	shopify_password = shopify_settings.get_password("password")

	frappe.reload_doc("shopify_integration", "doctype", "shopify_settings")
	frappe.reload_doc("shopify_integration", "doctype", "shopify_payout")
	setup_custom_fields()

	# get shop name
	url = urlparse(shopify_data.get("shopify_url"))
	subdomain = url.hostname.split(".")[0]
	if subdomain:
		shop_name = frappe.unscrub(subdomain.replace("-", " "))
	else:
		shop_name = "Shopify"

	# create new Shopify Settings document
	new_shop = frappe.new_doc("Shopify Settings")
	new_shop.update(shopify_data)
	new_shop.update({
		"shop_name": shop_name,
		"password": shopify_password,
		"item_group": get_root_of("Item Group")
	})
	new_shop.insert(ignore_permissions=True)

	# update Shopify Payout and linked Shopify documents
	for payout in frappe.get_all("Shopify Payout"):
		frappe.db.set_value("Shopify Payout", payout.name, "shop_name", new_shop.name)

		payout_doc = frappe.get_doc("Shopify Payout", payout.name)
		for transaction in payout_doc.transactions:
			if transaction.sales_order:
				frappe.db.set_value("Sales Order", transaction.sales_order,
					"shopify_settings", new_shop.name)
			if transaction.sales_invoice:
				frappe.db.set_value("Sales Invoice", transaction.sales_invoice,
					"shopify_settings", new_shop.name)
			if transaction.delivery_note:
				frappe.db.set_value("Delivery Note", transaction.delivery_note,
					"shopify_settings", new_shop.name)

	# # ref: https://github.com/ParsimonyGit/shipstation_integration/
	# update the "Is Shopify Store" check in Shipstation stores
	if "shipstation_integration" in frappe.get_installed_apps():
		mws_setup_marketplaces = frappe.get_all("Shipstation Store",
			filters={"marketplace_name": "Shopify"})
		for marketplace in mws_setup_marketplaces:
			frappe.db.set_value("Shipstation Store", marketplace.name,
				"is_shopify_store", True)
