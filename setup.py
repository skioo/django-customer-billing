#!/usr/bin/env python
from setuptools import setup

import billing

setup(
    name='django-customer-billing',
    version=billing.__version__,
    description='',
    long_description='',
    author='Nicholas Wolff',
    author_email='nwolff@gmail.com',
    url=billing.__URL__,
    download_url='https://pypi.python.org/pypi/django-customer-billing',
    packages=[
        'billing',
        'billing.actions',
        'billing.migrations',
        'billing.management.commands',
        'billing.signals',
    ],
    package_data={'billing': [
        'templates/admin/billing/*.html',
    ]},
    install_requires=[
        'Django>=2.0',
        'django-money<0.15',    # 0.15 contains imcompatible changes.
        'django-fsm',
        'djangorestframework',
        'django-import-export',
        'structlog',
        'typing',
        'progressbar2',
    ],
    license=billing.__licence__,
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Web Environment',
        'Framework :: Django :: 2.0',
        'Framework :: Django :: 2.1',
        'Framework :: Django :: 2.2',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
    ],
)
