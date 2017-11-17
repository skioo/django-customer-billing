# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-11-17 15:21
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0003_psp_uri_to_generic_relation'),
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='modified',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name='charge',
            name='modified',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name='creditcard',
            name='modified',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name='invoice',
            name='modified',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name='transaction',
            name='modified',
            field=models.DateTimeField(auto_now=True),
        ),
    ]
