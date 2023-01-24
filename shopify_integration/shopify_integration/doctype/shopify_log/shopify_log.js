/* global frappe, __ */

// Copyright (c) 2021, Parsimony, LLC and contributors
// For license information, please see license.txt

frappe.ui.form.on('Shopify Log', {
	refresh: (frm) => {
		if (frm.doc.request_data) {
			frm.add_custom_button('Resync', async () => {
				const response = await frappe.call({
					method: "shopify_integration.shopify_integration.doctype.shopify_log.shopify_log.resync",
					args: {
						shop_name: frm.doc.shop,
						method: frm.doc.method,
						name: frm.doc.name,
						request_data: frm.doc.request_data
					},
					freeze: true,
				})

				if (!response.exc) {
					frappe.msgprint(__("Order rescheduled for sync"));
				}
			}).addClass('btn-primary');
		}
	}
});
