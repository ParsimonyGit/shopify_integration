# -*- coding: utf-8 -*-
# Copyright (c) 2021, Parsimony, LLC and contributors
# For license information, please see license.txt

import json
from typing import TYPE_CHECKING, Dict, List, Union

import frappe
from frappe.model.document import Document

if TYPE_CHECKING:
	from shopify import Order

	from shopify_integration.shopify_integration.doctype.shopify_settings.shopify_settings import ShopifySettings


class ShopifyLog(Document):
	pass


def make_shopify_log(
	shop_name: str,
	status: str = "Queued",
	response_data: Union[str, Dict] = None,
	exception: Union[Exception, List] = None,
	rollback: bool = False,
):
	# if name not provided by log calling method then fetch existing queued state log
	make_new = False

	if not frappe.flags.log_id:
		make_new = True

	if rollback:
		frappe.db.rollback()

	if make_new:
		log = frappe.new_doc("Shopify Log").insert(ignore_permissions=True)
	else:
		log = frappe.get_doc("Shopify Log", frappe.flags.log_id)

	if not isinstance(response_data, str):
		response_data = json.dumps(response_data, sort_keys=True, indent=4)

	log.shop = shop_name
	log.message = get_message(exception)
	log.response_data = response_data
	log.traceback = frappe.get_traceback()
	log.status = status
	log.save(ignore_permissions=True)
	frappe.db.commit()


def get_message(exception: Exception):
	message = "Something went wrong while syncing"

	if hasattr(exception, "message"):
		message = exception.message
	elif hasattr(exception, "__str__"):
		message = exception.__str__()

	return message


@frappe.whitelist()
def resync(shop_name: str, method: str, name: str, request_data: str):
	frappe.db.set_value("Shopify Log", name, "status", "Queued", update_modified=False)

	request_data = json.loads(request_data)
	shopify_settings: "ShopifySettings" = frappe.get_doc("Shopify Settings", shop_name)

	order_id = request_data.get("id")
	orders: List["Order"] = shopify_settings.get_orders(order_id)
	order = orders[0]

	frappe.enqueue(method=method, queue='short', timeout=300, is_async=True,
		**{"shop_name": shop_name, "order": order, "log_id": name})
