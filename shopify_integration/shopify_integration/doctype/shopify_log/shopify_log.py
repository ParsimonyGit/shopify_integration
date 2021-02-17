# -*- coding: utf-8 -*-
# Copyright (c) 2021, Parsimony, LLC and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.model.document import Document


class ShopifyLog(Document):
	pass


def make_shopify_log(status="Queued", response_data=None, exception=None, rollback=False):
	# if name not provided by log calling method then fetch existing queued state log
	make_new = False

	if not frappe.flags.request_id:
		make_new = True

	if rollback:
		frappe.db.rollback()

	if make_new:
		log = frappe.new_doc("Shopify Log").insert(ignore_permissions=True)
	else:
		log = frappe.get_doc("Shopify Log", frappe.flags.request_id)

	if not isinstance(response_data, str):
		response_data = json.dumps(response_data, sort_keys=True, indent=4)

	log.message = get_message(exception)
	log.response_data = response_data
	log.traceback = frappe.get_traceback()
	log.status = status
	log.save(ignore_permissions=True)
	frappe.db.commit()


def get_message(exception):
	message = "Something went wrong while syncing"

	if hasattr(exception, 'message'):
		message = exception.message
	elif hasattr(exception, '__str__'):
		message = exception.__str__()

	return message


@frappe.whitelist()
def resync(method, name, request_data):
	frappe.db.set_value("Shopify Log", name, "status", "Queued", update_modified=False)
	frappe.enqueue(method=method, queue='short', timeout=300, is_async=True,
		**{"order": json.loads(request_data), "request_id": name})
