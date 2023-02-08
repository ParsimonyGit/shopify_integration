from typing import Union

from shopify import LineItem, Product, Variant

import frappe
from frappe.utils import cstr


def get_item_alias(shopify_item: Union[LineItem, Product, Variant]):
	# ref: https://github.com/ParsimonyGit/parsimony/
	# check if the Parsimony app is installed on the current site;
	# `frappe.db.table_exists` returns a false positive if any other
	# site on the bench has the Parsimony app installed instead
	if "parsimony" not in frappe.get_installed_apps():
		return

	sku = None
	if isinstance(shopify_item, LineItem):
		sku = (
			shopify_item.attributes.get("sku")
			or shopify_item.attributes.get("variant_id")
			or shopify_item.attributes.get("product_id")
			or shopify_item.attributes.get("title", "").strip()
		)
	elif isinstance(shopify_item, (Product, Variant)):
		product_id = variant_id = item_name = None
		shopify_sku = shopify_item.attributes.get("sku")
		item_title = shopify_item.attributes.get("title", "").strip()

		if isinstance(shopify_item, Product):
			product_id = shopify_item.id
			item_name = item_title
		elif isinstance(shopify_item, Variant):
			product_id = shopify_item.attributes.get("product_id")
			variant_id = shopify_item.id

		sku = cstr(shopify_sku or variant_id or product_id or item_name)

	if sku:
		item_aliases = frappe.get_all(
			"Item Alias",
			filters={"sku": sku},
			pluck="parent",
		)

		if item_aliases:
			return item_aliases[0]
