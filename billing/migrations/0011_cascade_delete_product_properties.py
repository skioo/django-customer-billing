# Generated by Django 2.0.1 on 2018-01-26 17:21

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0010_allow_empty_product_property_value'),
    ]

    operations = [
        migrations.AlterField(
            model_name='productproperty',
            name='charge',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='product_properties', to='billing.Charge'),
        ),
    ]
