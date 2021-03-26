from typing import TYPE_CHECKING

import frappe
from frappe import _
from frappe.utils import cstr

if TYPE_CHECKING:
	import shopify
	from erpnext.selling.doctype.customer.customer import Customer
	from shopify import Address, Order
	ShopifyCustomer = shopify.Customer


def validate_customer(shop_name: str, shopify_order: "Order"):
	customer = shopify_order.attributes.get("customer", frappe._dict())
	customer_id = customer.id
	if customer_id and not frappe.db.get_value("Customer", {"shopify_customer_id": customer_id}, "name"):
		create_customer(shop_name, customer)


def create_customer(shop_name: str, shopify_customer: "ShopifyCustomer"):
	from frappe.utils.nestedset import get_root_of

	if shopify_customer.attributes.get("first_name"):
		first_name = cstr(shopify_customer.first_name)
		last_name = cstr(shopify_customer.last_name)
		cust_name = f"{first_name} {last_name}"
	else:
		cust_name = shopify_customer.email

	try:
		customer: "Customer" = frappe.get_doc({
			"doctype": "Customer",
			"name": shopify_customer.id,
			"customer_name": cust_name,
			"shopify_customer_id": shopify_customer.id,
			"customer_group": frappe.db.get_value("Shopify Settings", shop_name, "customer_group"),
			"territory": get_root_of("Territory"),
			"customer_type": _("Individual")
		})
		customer.flags.ignore_mandatory = True
		customer.insert(ignore_permissions=True)

		if customer:
			create_customer_address(customer, shopify_customer)

		frappe.db.commit()
	except Exception as e:
		raise e


def create_customer_address(customer: "Customer", shopify_customer: "ShopifyCustomer"):
	if not shopify_customer.attributes.get("addresses"):
		return

	address: "Address"
	for i, address in enumerate(shopify_customer.addresses):
		address_title, address_type = get_address_title_and_type(customer.customer_name, i)
		try:
			frappe.get_doc({
				"doctype": "Address",
				"shopify_address_id": address.id,
				"address_title": address_title,
				"address_type": address_type,
				"address_line1": address.address1 or "Address 1",
				"address_line2": address.address2,
				"city": address.city or "City",
				"state": address.province,
				"pincode": address.zip,
				"country": address.country,
				"phone": address.phone,
				"email_id": shopify_customer.email,
				"links": [{
					"link_doctype": "Customer",
					"link_name": customer.name
				}]
			}).insert(ignore_mandatory=True)
		except Exception as e:
			raise e


def get_address_title_and_type(customer_name, index):
	address_type = _("Billing")
	address_title = customer_name

	address_name = f"{customer_name.strip()}-{address_type}"
	if frappe.db.exists("Address", address_name):
		address_title = f"{customer_name.strip()}-{index}"

	return address_title, address_type
