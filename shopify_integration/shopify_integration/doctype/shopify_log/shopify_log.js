// Copyright (c) 2021, Parsimony, LLC and contributors
// For license information, please see license.txt

frappe.ui.form.on("Shopify Log", {
	refresh: (frm) => {
		if (frm.doc.request_data && frm.doc.status === "Error") {
			frm.add_custom_button("Resync", async () => {
				const response = await frm.call({
					doc: frm.doc,
					method: "resync",
					freeze: true,
				});

				if (!response.exc) {
					frappe.msgprint(__("Order rescheduled for sync"));
				}
			}).addClass("btn-primary");
		}
	},
});
