/* global frappe, __ */

// Copyright (c) 2021, Parsimony, LLC and contributors
// For license information, please see license.txt

frappe.ui.form.on('Shopify Log', {
	refresh: function (frm) {
		if (frm.doc.request_data && frm.doc.status === 'Error') {
			frm.add_custom_button('Resync', function () {
				frappe.call({
					method: "shopify_integration.shopify_integration.doctype.shopify_log.shopify_log.resync",
					args: {
						method: frm.doc.method,
						name: frm.doc.name,
						request_data: frm.doc.request_data
					},
					callback: function (r) {
						frappe.msgprint(__("Order rescheduled for sync"))
					}
				})
			}).addClass('btn-primary');
		}
	}
});
