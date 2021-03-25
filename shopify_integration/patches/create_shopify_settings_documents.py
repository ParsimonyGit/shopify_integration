import frappe
from urllib.parse import urlparse
from frappe.utils.nestedset import get_root_of


def execute():
	# store data from original single document
	shopify_settings = frappe.get_doc("Shopify Settings")
	shopify_data = shopify_settings.as_dict(no_default_fields=True)
	shopify_password = shopify_settings.get_password("password")

	frappe.reload_doc("shopify_integration", "doctype", "shopify_settings")
	frappe.reload_doc("shopify_integration", "doctype", "shopify_payout")

	# get shop name
	url = urlparse(shopify_data.get("shopify_url"))
	subdomain = url.hostname.split('.')[0]
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

	# update Shopify Payouts and connect with new shop
	frappe.db.sql("""
		UPDATE
			`tabShopify Payout`
		SET
			shop_name = %(shop_name)s
	""", {
		'shop_name': new_shop.name
	})
