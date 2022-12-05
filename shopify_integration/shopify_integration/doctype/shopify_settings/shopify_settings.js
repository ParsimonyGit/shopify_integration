/* global frappe, __ */

// Copyright (c) 2021, Parsimony, LLC and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("erpnext_integrations.shopify_settings");
frappe.ui.form.on("Shopify Settings", {
	onload: (frm) => {
		frm.call("get_series").then(r => {
			$.each(r.message, (key, value) => {
				set_field_options(key, value);
			});
		});

		erpnext_integrations.shopify_settings.setup_queries(frm);
	},

	refresh: (frm) => {
		if (!frm.is_new()) {
			if (frm.doc.enable_shopify === 1) {
				frm.toggle_reqd("price_list", true);
				frm.toggle_reqd("warehouse", true);
				frm.toggle_reqd("company", true);
				frm.toggle_reqd("cost_center", true);
				frm.toggle_reqd("sales_order_series", true);
				frm.toggle_reqd("customer_group", true);

				frm.toggle_reqd("tax_account", true);
				frm.toggle_reqd("shipping_account", true);
				frm.toggle_reqd("cash_bank_account", true);
				frm.toggle_reqd("payment_fee_account", true);

				frm.toggle_reqd("sales_invoice_series", frm.doc.sync_sales_invoice);
				frm.toggle_reqd("delivery_note_series", frm.doc.sync_delivery_note);

				const base_shopify_url = frappe.utils.is_url(frm.doc.shopify_url)
					? frm.doc.shopify_url
					: `//${frm.doc.shopify_url}`

				if (frm.doc.app_type === "Custom") {
					frm.set_intro(`
						Syncing with Shopify requires the following API permissions in your
							<a target="_blank" href="${base_shopify_url}/admin/apps/development">custom apps</a>:
							</br></br>

						<strong>Products:</strong> Read access (read_products)</br>
						<strong>Orders:</strong> Read access (read_orders)</br>
						<strong>Payouts:</strong> Read access (read_shopify_payments_payouts)
					`);
				} else if (frm.doc.app_type === "Public") {
					frm.add_custom_button(__("Authorize"), () => {
						frappe.call({
							method: "shopify_integration.oauth.initiate_web_application_flow",
							args: { "settings": frm.doc },
							freeze: true,
							callback: function (r) {
								window.open(r.message, "_blank");
							}
						});
					});
				}

				frm.add_custom_button(__("Products"), () => {
					frm.call({
						doc: frm.doc,
						method: "sync_products",
						freeze: true,
						callback: (r) => {
							if (!r.exc) {
								frappe.msgprint(__("Product sync has been queued. This may take a few minutes."));
								frm.reload_doc();
							} else {
								frappe.msgprint(__("Something went wrong while trying to sync products. Please check the latest Shopify logs."))
							}
						}
					})
				}, __("Sync"));

				frm.add_custom_button(__("Payouts"), () => {
					frappe.prompt(
						[
							{
								"fieldname": "start_date",
								"fieldtype": "Datetime",
								"label": __("Payout Start Date"),
								"description": __("Defaults to the 'Last Sync Datetime' field"),
								"default": frm.doc.last_sync_datetime,
								"reqd": 1
							}
						],
						(values) => {
							const { start_date } = values;
							frm.call({
								doc: frm.doc,
								method: "sync_payouts",
								args: { "start_date": start_date },
								freeze: true,
								callback: (r) => {
									if (!r.exc) {
										frappe.msgprint(__("Payout sync has been queued. This may take a few minutes."));
										frm.reload_doc();
									} else {
										frappe.msgprint(__("Something went wrong while trying to sync payouts. Please check the latest Shopify logs."))
									}
								}
							})
						},
						__("Select Start Date")
					);
				}, __("Sync"));
			}
		}
	},
})

$.extend(erpnext_integrations.shopify_settings, {
	setup_queries: (frm) => {
		frm.set_query("warehouse", (doc) => {
			return {
				filters: {
					company: doc.company,
					is_group: "No"
				}
			}
		});

		frm.set_query("tax_account", (doc) => {
			return {
				query: "erpnext.controllers.queries.tax_account_query",
				filters: {
					account_type: ["Tax", "Chargeable", "Expense Account"],
					company: doc.company
				}
			}
		});

		frm.set_query("shipping_account", (doc) => {
			return {
				query: "erpnext.controllers.queries.tax_account_query",
				filters: {
					account_type: ["Tax", "Chargeable", "Expense Account"],
					company: doc.company
				}
			}
		});

		frm.set_query("payment_fee_account", (doc) => {
			return {
				query: "erpnext.controllers.queries.tax_account_query",
				filters: {
					account_type: ["Chargeable", "Expense Account"],
					company: doc.company
				}
			}
		});

		frm.set_query("cash_bank_account", (doc) => {
			return {
				filters: [
					["Account", "account_type", "in", ["Cash", "Bank"]],
					["Account", "root_type", "=", "Asset"],
					["Account", "is_group", "=", 0],
					["Account", "company", "=", doc.company]
				]
			}
		});

		frm.set_query("cost_center", (doc) => {
			return {
				filters: {
					company: doc.company,
					is_group: "No"
				}
			}
		});

		frm.set_query("price_list", () => {
			return { filters: { selling: 1 } }
		});
	}
})
