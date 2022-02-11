# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from . import __version__ as app_version

app_name = "shopify_integration"
app_title = "Shopify Integration"
app_publisher = "Parsimony, LLC"
app_description = "Shopify integration with ERPNext"
app_icon = "octicon octicon-file-directory"
app_color = "grey"
app_email = "developers@parsimony.com"
app_license = "MIT"

# Setup Wizard
# ------------
setup_wizard_stages = "shopify_integration.setup.get_setup_stages"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/shopify_integration/css/shopify_integration.css"
# app_include_js = "/assets/shopify_integration/js/shopify_integration.js"

# include js, css files in header of web template
# web_include_css = "/assets/shopify_integration/css/shopify_integration.css"
# web_include_js = "/assets/shopify_integration/js/shopify_integration.js"

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Website user home page (by function)
# get_website_user_home_page = "shopify_integration.utils.get_home_page"

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Installation
# ------------

# before_install = "shopify_integration.install.before_install"
# after_install = "shopify_integration.install.after_install"
before_migrate = "shopify_integration.setup.setup_custom_fields"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "shopify_integration.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

scheduler_events = {
	"daily_long": [
		"shopify_integration.payouts.sync_all_payouts"
	]
}

# Testing
# -------

# before_tests = "shopify_integration.install.before_tests"

# Overriding Methods
# ------------------------------

override_whitelisted_methods = {
	"frappe.integrations.doctype.connected_app.connected_app.callback": "shopify_integration.oauth.callback"
}
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "shopify_integration.task.get_dashboard_data"
# }
