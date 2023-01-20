# -*- coding: utf-8 -*-
# Copyright (c) 2021, Parsimony, LLC and contributors
# For license information, please see license.txt

import json
from typing import Dict, List, Optional, Union

import frappe
from frappe.model.document import Document


class ShopifyLog(Document):
	pass


def make_shopify_log(
	shop_name: str,
	status: str = "Queued",
	message: Optional[str] = None,
	response_data: Optional[Union[str, Dict]] = None,
	exception: Optional[Union[Exception, List]] = None,
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

	error_message = (
		message or get_message(exception) or "Something went wrong while syncing"
	)

	log.update(
		{
			"shop": shop_name,
			"message": error_message,
			"response_data": response_data,
			"traceback": frappe.get_traceback(),
			"status": status,
		}
	)

	log.save(ignore_permissions=True)
	frappe.db.commit()


def get_message(exception: Exception):
	if hasattr(exception, "message"):
		return exception.message
	elif hasattr(exception, "__str__"):
		return exception.__str__()


@frappe.whitelist()
def resync(shop_name: str, method: str, name: str, request_data: str):
	frappe.db.set_value("Shopify Log", name, "status", "Queued", update_modified=False)
	request_data = json.loads(request_data)

	if request_data.get("order_edit"):
		order_id = request_data.get("order_edit", {}).get("order_id")
		frappe.get_attr(method)(
			shop_name, order_id, request_data.get("order_edit"), name
		)
	else:
		order_id = request_data.get("id")
		frappe.get_attr(method)(shop_name, order_id, name)

	# frappe.enqueue(
	# 	method=method,
	# 	queue="short",
	# 	timeout=300,
	# 	is_async=True,
	# 	**{"shop_name": shop_name, "order_id": order_id, "log_id": name}
	# )
