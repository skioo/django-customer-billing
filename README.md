django-customer-billing
============

[![Build Status](https://travis-ci.org/skioo/django-customer-billing.svg?branch=master)](https://travis-ci.org/skioo/django-customer-billing)
[![PyPI version](https://badge.fury.io/py/django-customer-billing.svg)](https://badge.fury.io/py/django-customer-billing)
[![Requirements Status](https://requires.io/github/skioo/django-customer-billing/requirements.svg?branch=master)](https://requires.io/github/skioo/django-customer-billing/requirements/?branch=master)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)



Requirements
------------

* Python: 3.4 and over
* Django: 1.11 and over


Usage
-----

Add billing to your `INSTALLED_APPS`:

    INSTALLED_APPS = (
        ...
        'billing.apps.BillingConfig,
        ...
    )


Run the migrations: 

    ./manage.py migrate
    
