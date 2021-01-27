# -*- coding: utf-8 -*-

# get version from __version__ variable in shopify_integration/__init__.py
from shopify_integration import __version__ as version
from setuptools import setup, find_packages

with open('requirements.txt') as f:
	install_requires = f.read().strip().split('\n')

setup(
	name='shopify_integration',
	version=version,
	description='Shopify integration with ERPNext',
	author='Parsimony, LLC',
	author_email='developers@parsimony.com',
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
