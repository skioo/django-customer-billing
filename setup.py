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
    ],
    install_requires=[
        'Django>=1.11',
        'django-money',
        'django-fsm',
        'djangorestframework',
        'structlog',
        'typing',
        'progressbar2'
    ],
    license=billing.__licence__,
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Web Environment',
        'Framework :: Django :: 1.11',
        'Framework :: Django :: 2.0',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
    ],
)
