"""
Adapted from django-hordak.


``Total`` **instances (see below for more details)**:

    An account can hold multiple currencies, and a `Total`_ instance is how we represent this.

    A `Total`_ may contain one or more ``Money`` objects. There will be precisely one ``Money`` object
    for each currency which the account holds.

    `Total`_ objects may be added, subtracted etc. This will produce a new `Total`_ object containing a
    union of all the currencies involved in the calculation, even where the result was zero.

"""

import copy
from django.utils.translation import get_language
from django.utils.translation import to_locale
from moneyed import Money
from moneyed.localization import format_money
from rest_framework import serializers
from rest_framework.fields import DecimalField


class Total(object):
    """
    Accounts may have multiple currencies. This class represents these multi-currency
    Totals and provides math functionality. Totals can be added, subtracted,absolute'ed,
    and have their sign changed.

    Examples:

        Example use::

            Total([Money(100, 'USD'), Money(200, 'EUR')])

            # Or in short form
            Total(100, 'USD', 200, 'EUR')
    """

    def __init__(self, _money_obs=None, *args):
        all_args = [_money_obs] + list(args)
        if len(all_args) % 2 == 0:
            _money_obs = []
            for i in range(0, len(all_args) - 1, 2):
                _money_obs.append(Money(all_args[i], all_args[i + 1]))

        self._money_obs = tuple(_money_obs or [])
        self._by_currency = {m.currency.code: m for m in self._money_obs}
        if len(self._by_currency) != len(self._money_obs):
            raise ValueError('Duplicate currency provided. All Money instances must have a unique currency.')

    def __str__(self):
        def fmt(money):
            return format_money(money, locale=to_locale(get_language() or 'en-us'))

        return ', '.join(map(fmt, self._money_obs)) or 'No values'

    def __repr__(self):
        return 'Total: {}'.format(self.__str__())

    def __getitem__(self, currency):
        if hasattr(currency, 'code'):
            currency = currency.code
        elif not isinstance(currency, str) or len(currency) != 3:
            raise ValueError('Currencies must be a string of length three, not {}'.format(currency))

        try:
            return self._by_currency[currency]
        except KeyError:
            return Money(0, currency)

    def __add__(self, other):
        if not isinstance(other, Total):
            raise TypeError('Can only add/subtract Total instances, not Total and {}.'.format(type(other)))
        by_currency = copy.deepcopy(self._by_currency)
        for other_currency, other_money in other._by_currency.items():
            by_currency[other_currency] = other_money + self[other_currency]
        return self.__class__(by_currency.values())

    def __sub__(self, other):
        return self.__add__(-other)

    def __neg__(self):
        return self.__class__([-m for m in self._money_obs])

    def __pos__(self):
        return self.__class__([+m for m in self._money_obs])

    def __abs__(self):
        return self.__class__([abs(m) for m in self._money_obs])

    def __bool__(self):
        return any([bool(m) for m in self._money_obs])

    def __eq__(self, other):
        if other == 0:
            # Support comparing to integer/Decimal zero as it is useful
            return not self.__bool__()
        elif not isinstance(other, Total):
            raise TypeError('Can only compare Total objects to other '
                            'Total objects, not to type {}'.format(type(other)))
        return not self - other

    def __ne__(self, other):
        return not self.__eq__(other)

    def monies(self):
        """Get a list of the underlying ``Money`` instances

        Returns:
            ([Money]): A list of zero or more money instances. Currencies will be unique.
        """
        return [copy.copy(m) for m in self._money_obs]

    def nonzero_monies(self):
        """Get a list of the underlying ``Money`` instances that are not zero

        Returns:
            ([Money]): A list of zero or more money instances. Currencies will be unique.
        """
        return [copy.copy(m) for m in self._money_obs if m.amount != 0]

    def currencies(self):
        """Get all currencies, including those with zero values"""
        return [m.currency.code for m in self.monies() if m.amount]


class TotalSerializer(serializers.BaseSerializer):
    """
    Totals are serialized as a list of money instances.
    """
    amount_serializer = DecimalField(max_digits=12, decimal_places=2)

    def to_representation(self, obj):
        # We cannot use djmoney.contrib.django_rest_framework.MoneyField because a total is not a field.
        # So we replicate the output.
        return [{'amount': TotalSerializer.amount_serializer.to_representation(money.amount),
                 'amount_currency': money.currency.code} for money in obj.nonzero_monies()]


class TotalIncludingZeroSerializer(serializers.BaseSerializer):
    """
    Totals are serialized as a list of money instances.
    """
    amount_serializer = DecimalField(max_digits=12, decimal_places=2)

    def to_representation(self, obj):
        # We cannot use djmoney.contrib.django_rest_framework.MoneyField because a total is not a field.
        # So we replicate the output.
        return [{'amount': TotalSerializer.amount_serializer.to_representation(money.amount),
                 'amount_currency': money.currency.code} for money in obj.monies()]
