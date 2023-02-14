from typing import TYPE_CHECKING, Dict, List, Optional, Union

from shopify import Product, Variant

import frappe
from frappe import _
from frappe.utils import cint, cstr

from shopify_integration.hook_events.item import get_item_alias
from shopify_integration.shopify_integration.doctype.shopify_log.shopify_log import (
	make_shopify_log,
)

if TYPE_CHECKING:
	from shopify import LineItem, Option, Order

	from erpnext.stock.doctype.item.item import Item
	from erpnext.stock.doctype.item_attribute.item_attribute import ItemAttribute

	from shopify_integration.shopify_integration.doctype.shopify_settings.shopify_settings import (
		ShopifySettings,
	)

SHOPIFY_VARIANTS_ATTR_LIST = ["option1", "option2", "option3"]

# Weight units gathered from:
# https://shopify.dev/docs/admin-api/graphql/reference/products-and-collections/weightunit
WEIGHT_UOM_MAP = {"g": "Gram", "kg": "Kg", "oz": "Ounce", "lb": "Pound"}


def sync_items_from_shopify(shop_name: str):
	"""
	For a given Shopify store, sync all active products and create Item
	documents for missing products.

	:param shop_name: The name of the Shopify configuration for the store
	"""

	frappe.set_user("Administrator")
	shopify_settings: "ShopifySettings" = frappe.get_doc("Shopify Settings", shop_name)

	try:
		products = shopify_settings.get_products(status="active")
	except Exception as e:
		make_shopify_log(shop_name, status="Error", exception=e, rollback=True)
		return

	product: Product
	for product in products:
		if has_variants(product):
			# if template/variant creation is disabled, don't create parent items
			if shopify_settings.create_variant_items:
				make_item(shopify_settings, product)
		else:
			make_item(shopify_settings, product)

	try:
		variants = shopify_settings.get_variants(status="active")
	except Exception as e:
		make_shopify_log(shop_name, status="Error", exception=e, rollback=True)
		return

	for variant in variants:
		variant: Variant
		make_item(shopify_settings, variant)


def validate_items(shop_name: str, shopify_order: "Order"):
	"""
	Ensure that a Shopify order's items exist before processing the order.

	For every line item in the order, the order of priority for the reference field is:
	- Product ID
	- Variant ID
	- Item Title

	:param shop_name: The name of the Shopify configuration for the store
	:param shopify_order: The Shopify order data
	"""

	shopify_settings: "ShopifySettings" = frappe.get_doc("Shopify Settings", shop_name)
	for shopify_item in shopify_order.attributes.get("line_items", []):
		shopify_item: "LineItem"

		product_id = shopify_item.attributes.get("product_id")
		if product_id and not frappe.db.exists(
			"Item", {"shopify_product_id": product_id}
		):
			shopify_products: List[Product] = shopify_settings.get_products(product_id)
			for product in shopify_products:
				if has_variants(product):
					if shopify_settings.create_variant_items:
						# create the parent product item if it does not exist, and if template/variants
						# is enabled in the Shopify settings instance
						make_item(shopify_settings, product)
				else:
					make_item(shopify_settings, product)

		# create the child variant item if it does not exist
		variant_id = shopify_item.attributes.get("variant_id")
		if variant_id and not frappe.db.exists(
			"Item", {"shopify_variant_id": variant_id}
		):
			shopify_variants: List[Variant] = shopify_settings.get_variants(variant_id)
			for variant in shopify_variants:
				make_item(shopify_settings, variant)

		# Shopify somehow allows non-existent products to be added to an order;
		# for such cases, we create the item using the line item"s title
		if not (product_id or variant_id):
			line_item_title = shopify_item.attributes.get("title", "").strip()
			if line_item_title and not frappe.db.exists(
				"Item", {"item_code": line_item_title}
			):
				shopify_products: List[Product] = shopify_settings.get_products(
					title=shopify_item.attributes.get("title")
				)

				if not shopify_products:
					make_item_by_title(shopify_settings, line_item_title)
					return

				for product in shopify_products:
					make_item(shopify_settings, product)


def get_item_code(shopify_item: "LineItem") -> Optional[str]:
	item_code = get_item_alias(shopify_item)

	if not item_code:
		item_code = frappe.db.get_value(
			"Item", shopify_item.attributes.get("sku"), "item_code"
		)

	if not item_code:
		item_code = frappe.db.get_value(
			"Item", {"shopify_sku": shopify_item.attributes.get("sku")}, "item_code"
		)

	if not item_code:
		item_code = frappe.db.get_value(
			"Item",
			{"shopify_variant_id": shopify_item.attributes.get("variant_id")},
			"item_code",
		)

	if not item_code:
		item_code = frappe.db.get_value(
			"Item",
			{"shopify_product_id": shopify_item.attributes.get("product_id")},
			"item_code",
		)

	if not item_code:
		item_code = frappe.db.get_value(
			"Item",
			{"item_name": shopify_item.attributes.get("title", "").strip()},
			"item_code",
		)

	return item_code


def make_item(
	shopify_settings: "ShopifySettings", shopify_item: Union[Product, Variant]
):
	if shopify_settings.create_variant_items:
		attributes = []
		if isinstance(shopify_item, Product):
			attributes = create_product_attributes(shopify_item)

		if attributes:
			sync_item(shopify_settings, shopify_item, attributes)
			sync_item_variants(shopify_settings, shopify_item, attributes)
		else:
			sync_item(shopify_settings, shopify_item)
	else:
		# if template/variant creation is disabled, only create variant items
		if any(
			[
				isinstance(shopify_item, Product) and has_variants(shopify_item),
				isinstance(shopify_item, Variant),
			]
		):
			sync_item(shopify_settings, shopify_item)


def make_item_by_title(shopify_settings: "ShopifySettings", line_item_title: str):
	item_data = {
		"doctype": "Item",
		"is_stock_item": 1,
		"item_code": line_item_title,
		"item_name": line_item_title,
		"description": line_item_title,
		"shopify_description": line_item_title,
		"item_group": shopify_settings.item_group,
		"stock_uom": frappe.db.get_single_value("Stock Settings", "stock_uom"),
		"integration_doctype": "Shopify Settings",
		"integration_doc": shopify_settings.name,
		"item_defaults": [
			{
				"company": shopify_settings.company,
				"default_warehouse": shopify_settings.warehouse,
			}
		],
	}

	frappe.get_doc(item_data).insert(ignore_permissions=True)


def create_product_attributes(shopify_item: Product) -> List[Dict]:
	if not has_variants(shopify_item):
		return []

	item_attributes = []

	for attribute_option in shopify_item.attributes.get("options"):
		attribute_option: "Option"
		attribute_option_name = attribute_option.attributes.get("name")
		attribute_option_values = attribute_option.attributes.get("values") or []

		if not frappe.db.exists("Item Attribute", attribute_option_name):
			item_attr: "ItemAttribute" = frappe.new_doc("Item Attribute")
			item_attr.attribute_name = attribute_option_name
			update_item_attribute_values(item_attr, attribute_option_values)
			item_attr.insert()
			item_attributes.append({"attribute": attribute_option_name})
		else:
			# check for attribute values
			item_attr: "ItemAttribute" = frappe.get_doc(
				"Item Attribute", attribute_option_name
			)
			if not item_attr.numeric_values:
				update_item_attribute_values(item_attr, attribute_option_values)
				item_attr.save()
				item_attributes.append({"attribute": attribute_option_name})
			else:
				item_attributes.append(
					{
						"attribute": attribute_option_name,
						"from_range": item_attr.get("from_range"),
						"to_range": item_attr.get("to_range"),
						"increment": item_attr.get("increment"),
						"numeric_values": item_attr.get("numeric_values"),
					}
				)

	return item_attributes


def has_variants(product: Product):
	# Shopify creates a product variant for ALL products, whether they actually
	# have variants or not; the only way to tell if a product has variants is
	# to check against the attributes
	options = product.attributes.get("options")
	if options:
		option_values = [option.attributes.get("values") for option in options]
		# flatten list of option values
		option_values = [value for sublist in option_values for value in sublist]
		return "Default Title" not in option_values
	return False


def update_item_attribute_values(item_attr: "ItemAttribute", values: List[str]):
	if item_attr.is_new():
		existing_attribute_values = []
	else:
		existing_attribute_values = [
			attr.attribute_value.lower() for attr in item_attr.item_attribute_values
		]

	for attr_value in values:
		if attr_value.lower() not in existing_attribute_values:
			item_attr.append(
				"item_attribute_values",
				{"attribute_value": attr_value, "abbr": attr_value},
			)


def sync_item(
	shopify_settings: "ShopifySettings",
	shopify_item: Union[Product, Variant],
	attributes: List[Dict] = None,
	variant_of: str = str(),
	update: bool = False,
):
	"""
	Sync a Shopify product or variant and create a new Item document. If `update` is set
	to `True`, then any existing items found are updated as well.

	:param shopify_settings: The Shopify configuration for the store
	:param shopify_item: The Shopify `Product` or `Variant` data
	:param attributes: The item attributes for the Shopify item, defaults to None
	:param variant_of: (optional) If the item is a variant of an existing Item, defaults to an empty string
	:param update: (optional) Set if existing items should be updated, defaults to False
	"""

	product_id = variant_id = item_name = None
	shopify_sku = shopify_item.attributes.get("sku")
	item_title = shopify_item.attributes.get("title", "").strip()

	if isinstance(shopify_item, Product):
		product_id = shopify_item.id
		item_name = item_title
	elif isinstance(shopify_item, Variant):
		product_id = shopify_item.attributes.get("product_id")
		variant_id = shopify_item.id

		# attach the product name in front of the variant name
		if variant_of and shopify_settings.create_variant_items:
			product_name = frappe.db.get_value("Item", variant_of, "item_name")
			item_name = f"{product_name} - {item_title}"
		else:
			# TODO: should we check if the product exists on Shopify?
			products = shopify_settings.get_products(product_id, fields="title")
			if products:
				item_name = f"{products[0].title} - {item_title}"

	item_alias = get_item_alias(shopify_item)
	item_code = cstr(item_alias or shopify_sku or variant_id or product_id or item_name)
	item_description = shopify_item.attributes.get("body_html")
	item_has_variants = (
		has_variants(shopify_item) if shopify_settings.create_variant_items else False
	)

	item_data = {
		"shopify_product_id": cstr(product_id),
		"shopify_variant_id": cstr(variant_id),
		"disabled_on_shopify": False,
		# existing non-variant items default to `None`, if any other value is found,
		# an error is thrown for "Variant Of", which is a "Set Only Once" field
		"variant_of": variant_of if shopify_settings.create_variant_items else None,
		"is_stock_item": True,
		"item_code": item_code,
		"item_name": item_name,
		"description": item_description,
		"shopify_description": item_description,
		"item_group": shopify_settings.item_group,
		"marketplace_item_group": get_item_group(
			shopify_item.attributes.get("product_type")
		),
		"has_variants": item_has_variants,
		"stock_uom": WEIGHT_UOM_MAP.get(shopify_item.attributes.get("uom"))
		or frappe.db.get_single_value("Stock Settings", "stock_uom"),
		"shopify_sku": shopify_sku,
		"weight_uom": WEIGHT_UOM_MAP.get(shopify_item.attributes.get("weight_unit")),
		"weight_per_unit": shopify_item.attributes.get("weight"),
		"integration_doctype": "Shopify Settings",
		"integration_doc": shopify_settings.name,
		"item_defaults": [
			{
				"company": shopify_settings.company,
				"default_warehouse": shopify_settings.warehouse,
			}
		],
	}

	# form a list of attributes
	if variant_of and attributes and shopify_settings.create_variant_items:
		for attribute in attributes:
			attribute.update({"variant_of": variant_of})

	new_item_code = None
	if frappe.db.exists("Item", item_data.get("item_code")):
		if update:
			new_item_code = update_item(
				shopify_settings,
				shopify_item,
				item_data.get("item_code"),
				item_data,
				attributes,
			)
	else:
		new_item_code = create_item(
			shopify_settings, shopify_item, item_data, attributes
		)

	if (
		new_item_code
		and not item_has_variants
		and shopify_settings.update_price_in_erpnext_price_list
	):
		add_to_price_list(shopify_settings, shopify_item, new_item_code)

	frappe.db.commit()


def update_item(
	shopify_settings: "ShopifySettings",
	shopify_item: Union[Product, Variant],
	item_code: str,
	item_data: Dict,
	attributes: List[Dict],
):
	existing_item_doc: "Item" = frappe.get_doc("Item", item_code)
	existing_item_doc.update(item_data)

	# update item attributes for existing items without transactions;
	# if an item has transactions, its attributes cannot be changed
	if not existing_item_doc.stock_ledger_created():
		existing_attributes = [
			attribute.attribute for attribute in existing_item_doc.attributes
		]

		if attributes:
			for attribute in attributes:
				if attribute.get("attribute") not in existing_attributes:
					existing_item_doc.append("attributes", attribute)

	# add default item supplier from Shopify
	for default in existing_item_doc.item_defaults:
		if not default.default_supplier:
			default.default_supplier = get_supplier(shopify_settings, shopify_item)

	# fetch item image from Shopify
	if not existing_item_doc.image:
		existing_item_doc.image = get_item_image(shopify_settings, shopify_item)

	existing_item_doc.save(ignore_permissions=True)
	return existing_item_doc.name


def create_item(
	shopify_settings: "ShopifySettings",
	shopify_item: Union[Product, Variant],
	item_data: Dict,
	attributes: List[Dict],
):
	new_item: "Item" = frappe.new_doc("Item")
	new_item.update(item_data)
	new_item.update(
		{
			"attributes": attributes or [],
			"image": get_item_image(shopify_settings, shopify_item),
		}
	)

	# this fails during the `validate_name_with_item_group` call in item.py
	# if the item name matches with an existing item group; for such cases,
	# appending the item group into the item name
	if frappe.db.exists("Item Group", new_item.item_code):
		new_item.item_code = f"{new_item.item_code} ({new_item.item_group})"

	new_item.insert(ignore_permissions=True)

	# once the defaults have been generated, set the item supplier from Shopify
	supplier = get_supplier(shopify_settings, shopify_item)
	if supplier:
		if new_item.item_defaults:
			new_item.item_defaults[0].default_supplier = supplier
		else:
			new_item.append("item_defaults", {"default_supplier": supplier})

	return new_item.name


def sync_item_variants(
	shopify_settings: "ShopifySettings",
	shopify_item: Union[Product, Variant],
	attributes: List[Dict],
):
	product_id = None
	if isinstance(shopify_item, Product):
		product_id = shopify_item.id
	elif isinstance(shopify_item, Variant):
		product_id = shopify_item.attributes.get("product_id")

	if not product_id:
		return

	template_item = frappe.db.get_value(
		"Item",
		filters={"shopify_product_id": product_id},
		fieldname=["name", "stock_uom"],
		as_dict=True,
	)

	if template_item:
		variant: Variant
		for variant in shopify_item.attributes.get("variants", []):
			for index, variant_attr in enumerate(SHOPIFY_VARIANTS_ATTR_LIST):
				if index < len(attributes) and variant.attributes.get(variant_attr):
					attributes[index].update(
						{
							"attribute_value": get_attribute_value(
								variant.attributes.get(variant_attr),
								attributes[index],
							)
						}
					)

			sync_item(
				shopify_settings=shopify_settings,
				shopify_item=variant,
				attributes=attributes,
				variant_of=template_item.name,
				update=True,
			)


def get_attribute_value(variant_attr_val: str, attribute: Dict = None):
	if not attribute or not attribute.get("attribute"):
		return cint(variant_attr_val)

	attribute_values = frappe.get_all(
		"Item Attribute Value",
		filters={"parent": attribute.get("attribute")},
		or_filters={"abbr": variant_attr_val, "attribute_value": variant_attr_val},
		pluck="attribute_value",
	)

	if not attribute_values:
		return cint(variant_attr_val)

	return attribute_values[0]


def get_item_group(product_type: str = str()):
	from frappe.utils.nestedset import get_root_of

	parent_item_group = get_root_of("Item Group")
	if product_type:
		if not frappe.db.get_value("Item Group", product_type, "name"):
			item_group = frappe.get_doc(
				{
					"doctype": "Item Group",
					"item_group_name": product_type,
					"parent_item_group": parent_item_group,
					"is_group": "No",
				}
			).insert()
			return item_group.name
		return product_type
	return parent_item_group


def add_to_price_list(
	shopify_settings: "ShopifySettings",
	shopify_item: Union[Product, Variant],
	item_code: str,
):
	rate = 0
	if isinstance(shopify_item, Product):
		variants = shopify_item.attributes.get("variants", [])
		if variants:
			rate = variants[0].attributes.get("price") or 0
	elif isinstance(shopify_item, Variant):
		rate = shopify_item.attributes.get("price") or 0

	item_price_name = frappe.db.get_value(
		"Item Price",
		{"item_code": item_code, "price_list": shopify_settings.price_list},
		"name",
	)

	if item_price_name:
		item_rate = frappe.get_doc("Item Price", item_price_name)
		item_rate.price_list_rate = rate
		item_rate.save()
	else:
		item_rate = frappe.new_doc("Item Price")
		item_rate.price_list = shopify_settings.price_list
		item_rate.item_code = item_code
		item_rate.price_list_rate = rate
		item_rate.insert()


def get_item_image(
	shopify_settings: "ShopifySettings", shopify_item: Union[Product, Variant]
):
	image_url = None
	products = []

	if isinstance(shopify_item, Product):
		products = [shopify_item]
	elif isinstance(shopify_item, Variant):
		# TODO: should we check if the product exists on Shopify?
		products = shopify_settings.get_products(
			shopify_item.attributes.get("product_id"), fields="image"
		)

	product: Product
	for product in products:
		if product.attributes.get("image"):
			image_url = product.attributes.get("image").attributes.get("src")
			break

	return image_url


def get_supplier(
	shopify_settings: "ShopifySettings", shopify_item: Union[Product, Variant]
):
	supplier = vendor = str()

	# only Shopify products are assigned vendors
	if isinstance(shopify_item, Product):
		products = [shopify_item]
	elif isinstance(shopify_item, Variant):
		products: List[Product] = shopify_settings.get_products(
			shopify_item.attributes.get("product_id"), fields="vendor"
		)

	for product in products:
		if product.attributes.get("vendor"):
			vendor = product.attributes.get("vendor")
			break

	if vendor:
		suppliers = frappe.get_all(
			"Supplier",
			or_filters={
				"name": vendor,
				"supplier_name": vendor,
				"shopify_supplier_id": vendor.lower(),
			},
		)

		if not suppliers:
			supplier = frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": vendor,
					"shopify_supplier_id": vendor.lower(),
					"supplier_group": get_supplier_group(),
				}
			).insert()
			return supplier.name
		return suppliers[0].name
	return supplier


def get_supplier_group():
	supplier_group = frappe.db.get_value("Supplier Group", _("Shopify Supplier"))
	if not supplier_group:
		supplier_group = frappe.get_doc(
			{"doctype": "Supplier Group", "supplier_group_name": _("Shopify Supplier")}
		).insert()
		return supplier_group.name
	return supplier_group
