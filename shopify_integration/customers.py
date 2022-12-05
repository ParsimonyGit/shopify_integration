from typing import TYPE_CHECKING

import frappe
from frappe import _
from frappe.utils import cstr

if TYPE_CHECKING:
	from erpnext.selling.doctype.customer.customer import Customer
	from shopify import Address, Customer as ShopifyCustomer, Order


def validate_customer(shop_name: str, shopify_order: "Order"):
	customer = shopify_order.attributes.get("customer", frappe._dict())
	if customer.id and not frappe.db.get_value(
		"Customer", {"shopify_customer_id": customer.id}, "name"
	):
		create_customer(shop_name, customer)


def create_customer(shop_name: str, shopify_customer: "ShopifyCustomer"):
	from frappe.utils.nestedset import get_root_of

	if shopify_customer.attributes.get("first_name"):
		first_name = cstr(shopify_customer.first_name)
		last_name = cstr(shopify_customer.last_name)
		cust_name = f"{first_name} {last_name}"
	else:
		cust_name = shopify_customer.attributes.get("email")

	try:
		customer: "Customer" = frappe.get_doc(
			{
				"doctype": "Customer",
				"name": shopify_customer.id,
				"customer_name": cust_name,
				"shopify_customer_id": shopify_customer.id,
				"customer_group": frappe.db.get_value(
					"Shopify Settings", shop_name, "customer_group"
				),
				"territory": get_root_of("Territory"),
				"customer_type": _("Individual"),
			}
		)
		customer.flags.ignore_mandatory = True
		customer.insert(ignore_permissions=True)

		if customer:
			create_customer_address(customer, shopify_customer)

		frappe.db.commit()
	except Exception as e:
		raise e


def create_customer_address(customer: "Customer", shopify_customer: "ShopifyCustomer"):
	addresses = shopify_customer.attributes.get("addresses") or []

	if not addresses:
		default_address = shopify_customer.attributes.get("default_address")
		if default_address:
			addresses.append(default_address)

	address: "Address"
	for index, address in enumerate(addresses):
		frappe.get_doc(
			{
				"doctype": "Address",
				"shopify_address_id": address.id,
				"address_title": get_address_title(customer.customer_name, index),
				"address_type": "Billing",
				"address_line1": address.address1 or "Address 1",
				"address_line2": address.address2,
				"city": address.city or "City",
				"state": address.province,
				"pincode": address.zip,
				"country": address.country,
				"phone": address.phone,
				"email_id": shopify_customer.email,
				"links": [{"link_doctype": "Customer", "link_name": customer.name}],
			}
		).insert(ignore_mandatory=True)


def get_address_title(customer_name: str, index: int):
	address_type = _("Billing")
	address_title = customer_name

	address_name = f"{customer_name.strip()}-{address_type}"
	if frappe.db.exists("Address", address_name):
		address_title = f"{customer_name.strip()}-{index}"

	return address_title
