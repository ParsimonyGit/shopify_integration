import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def get_setup_stages(args=None):
	return [
		{
			"status": _("Setting up Shopify"),
			"fail_msg": _("Failed to create Shopify masters"),
			"tasks": [
				{
					"fn": setup_custom_fields,
					"args": args,
					"fail_msg": _("Failed to create Shopify custom fields")
				}
			]
		}
	]


def setup_custom_fields(args=None):
	custom_fields = {
		"Customer": [
			dict(fieldname="shopify_customer_id", label="Shopify Customer ID",
				fieldtype="Data", insert_after="series", read_only=1,
				print_hide=1, translatable=0)
		],
		"Supplier": [
			dict(fieldname="shopify_supplier_id", label="Shopify Supplier ID",
				fieldtype="Data", insert_after="supplier_name", read_only=1,
				print_hide=1, translatable=0)
		],
		"Address": [
			dict(fieldname="shopify_address_id", label="Shopify Address ID",
				fieldtype="Data", insert_after="fax", read_only=1,
				print_hide=1, translatable=0)
		],
		"Item": [
			# Shopify details
			dict(fieldname="shopify_product_id", label="Shopify Product ID",
				fieldtype="Data", insert_after="item_code", read_only=1, print_hide=1,
				translatable=0),
			dict(fieldname="shopify_variant_id", label="Shopify Variant ID",
				fieldtype="Data", insert_after="item_code", read_only=1, print_hide=1,
				translatable=0),
			dict(fieldname="shopify_sku", label="Shopify SKU", fieldtype="Data",
				insert_after="shopify_variant_id", read_only=1, print_hide=1, translatable=0),
			dict(fieldname="disabled_on_shopify", label="Disabled on Shopify",
				fieldtype="Check", insert_after="disabled", read_only=1, print_hide=1),
			dict(fieldname="marketplace_item_group", label="Marketplace Item Group",
				fieldtype="Data", insert_after="item_group", read_only=1, print_hide=1,
				translatable=0),
			dict(fieldname="shopify_description", label="Shopify Description",
				fieldtype="Text Editor", insert_after="description", read_only=1,
				print_hide=1, translatable=0),

			# Integration section
			dict(fieldname="sb_integration", label="Integration Details",
				fieldtype="Section Break", insert_after="description", collapsible=1),
			dict(fieldname="integration_doctype", label="Integration DocType",
				fieldtype="Link", options="DocType", insert_after="sb_integration",
				hidden=1, print_hide=1),
			dict(fieldname="integration_doc", label="Integration Doc", fieldtype="Dynamic Link",
				insert_after="integration_doctype", options="integration_doctype", read_only=1,
				print_hide=1),
		],
		"Sales Order": [
			dict(fieldname="sb_shopify", label="Shopify", fieldtype="Section Break",
				insert_after="tax_id", collapsible=0),
			dict(fieldname="shopify_settings", label="Shopify Settings",
				fieldtype="Link", options="Shopify Settings", insert_after="sb_shopify",
				read_only=1, print_hide=1),
			dict(fieldname="shopify_order_number", label="Shopify Order Number",
				fieldtype="Data", insert_after="shopify_settings",
				read_only=1, print_hide=1, translatable=0),
			dict(fieldname="cb_shopify", fieldtype="Column Break",
				insert_after="shopify_order_number"),
			dict(fieldname="shopify_order_id", label="Shopify Order ID",
				fieldtype="Data", insert_after="cb_shopify",
				read_only=1, print_hide=1, translatable=0),
			dict(fieldname="shopify_order_name", label="Shopify Order Name",
				fieldtype="Data", insert_after="shopify_order_id",
				read_only=1, print_hide=1, translatable=0),
		],
		"Sales Order Item": [
			dict(
				fieldname="shopify_order_item_id",
				label="Shopify Order Item ID",
				fieldtype="Data",
				insert_after="warehouse",
				read_only=True,
				print_hide=True,
				translatable=False,
			),
		],
		"Sales Invoice": [
			dict(fieldname="sb_shopify", label="Shopify", fieldtype="Section Break",
				insert_after="cost_center", collapsible=0),
			dict(fieldname="shopify_settings", label="Shopify Settings",
				fieldtype="Link", options="Shopify Settings", insert_after="sb_shopify",
				read_only=1, print_hide=1),
			dict(fieldname="shopify_order_number", label="Shopify Order Number",
				fieldtype="Data", insert_after="shopify_settings",
				read_only=1, print_hide=1, translatable=0),
			dict(fieldname="cb_shopify", fieldtype="Column Break",
				insert_after="shopify_order_number"),
			dict(fieldname="shopify_order_id", label="Shopify Order ID",
				fieldtype="Data", insert_after="cb_shopify",
				read_only=1, print_hide=1, translatable=0),
			dict(fieldname="shopify_order_name", label="Shopify Order Name",
				fieldtype="Data", insert_after="shopify_order_id",
				read_only=1, print_hide=1, translatable=0),
		],
		"Sales Invoice Item": [
			dict(
				fieldname="shopify_order_item_id",
				label="Shopify Order Item ID",
				fieldtype="Data",
				insert_after="sales_order",
				read_only=True,
				print_hide=True,
				translatable=False,
			),
		],
		"Delivery Note": [
			dict(fieldname="sb_shopify", label="Shopify", fieldtype="Section Break",
				insert_after="return_against", collapsible=0),
			dict(fieldname="shopify_settings", label="Shopify Settings",
				fieldtype="Link", options="Shopify Settings", insert_after="sb_shopify",
				read_only=1, print_hide=1),
			dict(fieldname="shopify_order_number", label="Shopify Order Number",
				fieldtype="Data", insert_after="shopify_settings",
				read_only=1, print_hide=1, translatable=0),
			dict(fieldname="cb_shopify", fieldtype="Column Break",
				insert_after="shopify_order_number"),
			dict(fieldname="shopify_order_id", label="Shopify Order ID",
				fieldtype="Data", insert_after="cb_shopify",
				read_only=1, print_hide=1, translatable=0),
			dict(fieldname="shopify_order_name", label="Shopify Order Name",
				fieldtype="Data", insert_after="shopify_order_id",
				read_only=1, print_hide=1, translatable=0),
			dict(fieldname="shopify_fulfillment_id", label="Shopify Fulfillment ID",
				fieldtype="Data", insert_after="shopify_order_name",
				read_only=1, print_hide=1, translatable=0),
		],
		"Delivery Note Item": [
			dict(
				fieldname="shopify_order_item_id",
				label="Shopify Order Item ID",
				fieldtype="Data",
				insert_after="against_sales_order",
				read_only=True,
				print_hide=True,
				translatable=False,
			),
		],
	}

	# ref: https://github.com/ParsimonyGit/shipstation_integration/
	# check if the Shipstation app is installed on the current site;
	# `frappe.db.table_exists` returns a false positive if any other
	# site on the bench has the Shipstation app installed instead
	if "shipstation_integration" in frappe.get_installed_apps():
		custom_fields.update({
			"Shipstation Store": [
				dict(fieldname="sb_shopify", label="Shopify", fieldtype="Section Break",
					insert_after="amazon_marketplace", read_only=1),
				dict(fieldname="is_shopify_store", label="Is Shopify Store", fieldtype="Check",
					insert_after="sb_shopify", read_only=1, print_hide=1),
				dict(fieldname="shopify_store", label="Shopify Store", fieldtype="Link",
					options="Shopify Settings", insert_after="is_shopify_store",
					depends_on="eval:doc.is_shopify_store", print_hide=1)
			]
		})

	create_custom_fields(custom_fields)
