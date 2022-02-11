#!/bin/bash

bench init \
--frappe-branch version-13 \
--skip-redis-config-generation \
--ignore-exist \
--skip-assets \
shopify-bench

cd shopify-bench

bench get-app http://github.com/frappe/erpnext --branch version-13 --skip-assets
bench get-app shopify_integration /tmp/shopify_integration --skip-assets

bench set-mariadb-host 127.0.0.1
bench set-redis-cache-host 127.0.0.1:6379
bench set-redis-queue-host 127.0.0.1:6379
bench set-redis-socketio-host 127.0.0.1:6379

bench new-site dev.localhost \
--mariadb-root-password 123 \
--admin-password admin \
--no-mariadb-socket

bench use dev.localhost
bench clear-cache

bench install-app erpnext
bench install-app shopify_integration
bench --site dev.localhost execute erpnext.setup.utils.before_tests