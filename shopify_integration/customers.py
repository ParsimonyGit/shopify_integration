import frappe
from frappe import _
from frappe.utils import cstr


def validate_customer(shopify_order):
	customer_id = shopify_order.get("customer", {}).get("id")
	if customer_id and not frappe.db.get_value("Customer", {"shopify_customer_id": customer_id}, "name"):
		create_customer(shopify_order.get("customer"))


def create_customer(shopify_customer):
	from frappe.utils.nestedset import get_root_of

	shopify_settings = frappe.get_single("Shopify Settings")

	if shopify_customer.get("first_name"):
		first_name = cstr(shopify_customer.get("first_name"))
		last_name = cstr(shopify_customer.get("last_name"))
		cust_name = f"{first_name} {last_name}"
	else:
		cust_name = shopify_customer.get("email")

	try:
		customer = frappe.get_doc({
			"doctype": "Customer",
			"name": shopify_customer.get("id"),
			"customer_name": cust_name,
			"shopify_customer_id": shopify_customer.get("id"),
			"customer_group": shopify_settings.customer_group,
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


def create_customer_address(customer, shopify_customer):
	if not shopify_customer.get("addresses"):
		return

	for i, address in enumerate(shopify_customer.get("addresses")):
		address_title, address_type = get_address_title_and_type(customer.customer_name, i)
		try:
			frappe.get_doc({
				"doctype": "Address",
				"shopify_address_id": address.get("id"),
				"address_title": address_title,
				"address_type": address_type,
				"address_line1": address.get("address1") or "Address 1",
				"address_line2": address.get("address2"),
				"city": address.get("city") or "City",
				"state": address.get("province"),
				"pincode": address.get("zip"),
				"country": address.get("country"),
				"phone": address.get("phone"),
				"email_id": shopify_customer.get("email"),
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
