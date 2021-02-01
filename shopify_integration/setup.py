from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def get_setup_stages(args=None):
	return [
		{
			'status': _('Setting up Shopify'),
			'fail_msg': _('Failed to create Shopify masters'),
			'tasks': [
				{
					'fn': setup_custom_fields,
					'args': args,
					'fail_msg': _("Failed to create Shopify custom fields")
				}
			]
		}
	]


def setup_custom_fields():
	custom_fields = {
		"Customer": [
			dict(fieldname='shopify_customer_id', label='Shopify Customer ID',
				fieldtype='Data', insert_after='series', read_only=1, print_hide=1)
		],
		"Supplier": [
			dict(fieldname='shopify_supplier_id', label='Shopify Supplier ID',
				fieldtype='Data', insert_after='supplier_name', read_only=1, print_hide=1)
		],
		"Address": [
			dict(fieldname='shopify_address_id', label='Shopify Address ID',
				fieldtype='Data', insert_after='fax', read_only=1, print_hide=1)
		],
		"Item": [
			dict(fieldname='shopify_variant_id', label='Shopify Variant ID',
				fieldtype='Data', insert_after='item_code', read_only=1, print_hide=1),
			dict(fieldname='shopify_product_id', label='Shopify Product ID',
				fieldtype='Data', insert_after='item_code', read_only=1, print_hide=1),
			dict(fieldname='shopify_description', label='Shopify Description',
				fieldtype='Text Editor', insert_after='description', read_only=1, print_hide=1),
			dict(fieldname='disabled_on_shopify', label='Disabled on Shopify',
				fieldtype='Check', insert_after='disabled', read_only=1, print_hide=1)
		],
		"Sales Order": [
			dict(fieldname='shopify_order_id', label='Shopify Order ID',
				fieldtype='Data', insert_after='title', read_only=1, print_hide=1)
		],
		"Delivery Note": [
			dict(fieldname='shopify_order_id', label='Shopify Order ID',
				fieldtype='Data', insert_after='title', read_only=1, print_hide=1),
			dict(fieldname='shopify_fulfillment_id', label='Shopify Fulfillment ID',
				fieldtype='Data', insert_after='title', read_only=1, print_hide=1)
		],
		"Sales Invoice": [
			dict(fieldname='shopify_order_id', label='Shopify Order ID',
				fieldtype='Data', insert_after='title', read_only=1, print_hide=1)
		]
	}

	create_custom_fields(custom_fields)
