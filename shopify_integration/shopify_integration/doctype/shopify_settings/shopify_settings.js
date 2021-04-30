/* global frappe, __ */

// Copyright (c) 2021, Parsimony, LLC and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("erpnext_integrations.shopify_settings");
frappe.ui.form.on("Shopify Settings", {
	onload: function (frm) {
		frm.call("get_series").then(r => {
			$.each(r.message, function (key, value) {
				set_field_options(key, value);
			});
		});

		erpnext_integrations.shopify_settings.setup_queries(frm);
	},

	refresh: function (frm) {
		if (!frm.is_new() && frm.doc.enable_shopify === 1) {
			frm.toggle_reqd("price_list", true);
			frm.toggle_reqd("warehouse", true);
			frm.toggle_reqd("company", true);
			frm.toggle_reqd("cost_center", true);
			frm.toggle_reqd("sales_order_series", true);
			frm.toggle_reqd("customer_group", true);
			frm.toggle_reqd("shared_secret", true);

			frm.toggle_reqd("tax_account", true);
			frm.toggle_reqd("shipping_account", true);
			frm.toggle_reqd("cash_bank_account", true);
			frm.toggle_reqd("payment_fee_account", true);

			frm.toggle_reqd("sales_invoice_series", frm.doc.sync_sales_invoice);
			frm.toggle_reqd("delivery_note_series", frm.doc.sync_delivery_note);

			const base_shopify_url = frappe.utils.is_url(frm.doc.shopify_url)
				? frm.doc.shopify_url
				: `//${frm.doc.shopify_url}`

			frm.set_intro(`
				Syncing with Shopify requires the following API permissions in your
					<a target="_blank" href="${base_shopify_url}/admin/apps/private">private apps</a>:
					</br></br>

				<strong>Products:</strong> Read access (read_products)</br>
				<strong>Orders:</strong> Read access (read_orders)</br>
				<strong>Payouts:</strong> Read access (read_shopify_payments_payouts)
			`);
		}

		if (frm.doc.enable_shopify) {
			frm.add_custom_button(__("Products"), function () {
				frm.call({
					doc: frm.doc,
					method: "sync_products",
					freeze: true,
					callback: function (r) {
						if (!r.exc) {
							frappe.msgprint(__("Product sync has been queued. This may take a few minutes."));
							frm.reload_doc();
						} else {
							frappe.msgprint(__("Something went wrong while trying to sync products. Please check the latest Shopify logs."))
						}
					}
				})
			}, __("Sync"));

			frm.add_custom_button(__("Payouts"), function () {
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
						let start_date = values.start_date;
						frm.call({
							doc: frm.doc,
							method: "sync_payouts",
							args: { "start_date": start_date },
							freeze: true,
							callback: function (r) {
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
	},

	app_type: function (frm) {
		frm.toggle_reqd("api_key", (frm.doc.app_type === "Private"));
		frm.toggle_reqd("password", (frm.doc.app_type === "Private"));
	}
})

$.extend(erpnext_integrations.shopify_settings, {
	setup_queries: function (frm) {
		frm.set_query("warehouse", function (doc) {
			return {
				filters: {
					company: doc.company,
					is_group: "No"
				}
			}
		});

		frm.set_query("tax_account", function (doc) {
			return {
				query: "erpnext.controllers.queries.tax_account_query",
				filters: {
					account_type: ["Tax", "Chargeable", "Expense Account"],
					company: doc.company
				}
			}
		});

		frm.set_query("shipping_account", function (doc) {
			return {
				query: "erpnext.controllers.queries.tax_account_query",
				filters: {
					account_type: ["Tax", "Chargeable", "Expense Account"],
					company: doc.company
				}
			}
		});

		frm.set_query("payment_fee_account", function (doc) {
			return {
				query: "erpnext.controllers.queries.tax_account_query",
				filters: {
					account_type: ["Chargeable", "Expense Account"],
					company: doc.company
				}
			}
		});

		frm.set_query("cash_bank_account", function (doc) {
			return {
				filters: [
					["Account", "account_type", "in", ["Cash", "Bank"]],
					["Account", "root_type", "=", "Asset"],
					["Account", "is_group", "=", 0],
					["Account", "company", "=", doc.company]
				]
			}
		});

		frm.set_query("cost_center", function (doc) {
			return {
				filters: {
					company: doc.company,
					is_group: "No"
				}
			}
		});

		frm.set_query("price_list", function () {
			return { filters: { selling: 1 } }
		});
	}
})
