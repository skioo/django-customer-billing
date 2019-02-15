from unittest import TestCase

from moneyed import Money
from pytest import raises

from billing.total import Total, TotalSerializer, TotalIncludingZeroSerializer


class TotalTest(TestCase):
    def test_unique_currency(self):
        with raises(ValueError):
            Total([Money(0, 'USD'), Money(0, 'USD')])

    def test_init_args(self):
        t = Total(100, 'USD', 200, 'EUR', 300, 'GBP')
        assert t['USD'].amount == 100
        assert t['EUR'].amount == 200
        assert t['GBP'].amount == 300

    def test_add(self):
        t1 = Total(100, 'USD', 100, 'EUR')
        t2 = Total(80, 'USD', 150, 'GBP')
        t = t1 + t2
        assert t['USD'].amount == 180
        assert t['EUR'].amount == 100
        assert t['GBP'].amount == 150

    def test_sub(self):
        t1 = Total(100, 'USD', 100, 'EUR')
        t2 = Total(80, 'USD', 150, 'GBP')
        t = t1 - t2
        assert t['USD'].amount == 20
        assert t['EUR'].amount == 100
        assert t['GBP'].amount == -150

    def test_sub_rev(self):
        t1 = Total(100, 'USD', 100, 'EUR')
        t2 = Total(80, 'USD', 150, 'GBP')
        t = t2 - t1
        assert t['USD'].amount == -20
        assert t['EUR'].amount == -100
        assert t['GBP'].amount == 150

    def test_neg(self):
        t1 = Total(100, 'USD', 100, 'EUR')
        t = -t1
        assert t['USD'].amount == -100
        assert t['EUR'].amount == -100
        assert t['GBP'].amount == 0

    def test_pos(self):
        t1 = Total(100, 'USD', 100, 'EUR')
        t = +t1
        assert t['USD'].amount == 100
        assert t['EUR'].amount == 100
        assert t['GBP'].amount == 0

    def test_abs(self):
        total_neg = Total(-10, 'USD', 20, 'GBP')
        t = abs(total_neg)
        assert t['USD'].amount == 10
        assert t['GBP'].amount == 20
        assert t['EUR'].amount == 0

    def test_bool(self):
        assert not bool(Total())
        assert not bool(Total(0, 'USD'))
        assert bool(Total(100, 'USD'))
        assert bool(Total(0, 'USD', 100, 'EUR'))
        assert not bool(Total(0, 'USD', 0, 'EUR'))

    def test_eq(self):
        assert Total() == Total()
        assert Total(0, 'USD') == Total()

        t1 = Total(100, 'USD', 100, 'EUR')
        t2 = Total(80, 'USD', 150, 'GBP')
        assert t1 == +t1
        assert not (t1 == t2)
        assert Total(100, 'USD') == Total(100, 'USD')
        assert Total(100, 'USD', 0, 'EUR') == Total(100, 'USD')

        assert not (Total(100, 'USD', 10, 'EUR') == Total(100, 'USD'))

    def test_eq_zero(self):
        assert Total() == 0
        assert Total(0, 'USD') == 0
        assert Total(0, 'USD', 0, 'CHF') == 0
        assert not (Total(100, 'USD', 100, 'EUR') == 0)

    def test_neq(self):
        assert not (Total() != Total())
        assert not (Total(0, 'USD') != Total())

        t1 = Total(100, 'USD', 100, 'EUR')
        t2 = Total(80, 'USD', 150, 'GBP')
        assert not (t1 != +t1)
        assert t1 != t2
        assert not (Total([Money(100, 'USD')]) != Total([Money(100, 'USD')]))
        assert not (Total([Money(100, 'USD'), Money(0, 'EUR')]) != Total([Money(100, 'USD')]))

        assert Total([Money(100, 'USD'), Money(10, 'EUR')]) != Total([Money(100, 'USD')])

    def test_currencies(self):
        t1 = Total(100, 'USD', 100, 'EUR')
        assert t1.currencies() == ['USD', 'EUR']

        t2 = Total(80, 'USD', 150, 'GBP')
        assert t2.currencies() == ['USD', 'GBP']

    def test_monies(self):
        t1 = Total(100, 'USD', 0, 'EUR')
        assert t1.monies() == [Money(100, 'USD'), Money(0, 'EUR')]
        assert t1.nonzero_monies() == [Money(100, 'USD')]


class TotalSerializerTest(TestCase):
    def test_serialize(self):
        t = Total(100, 'USD', -90, 'EUR')
        assert TotalSerializer(t).data == [
            {'amount': '100.00', 'amount_currency': 'USD'},
            {'amount': '-90.00', 'amount_currency': 'EUR'}
        ]

    def test_zero_value(self):
        t = Total(0, 'EUR')
        assert TotalSerializer(t).data == []
        assert TotalIncludingZeroSerializer(t).data == [
            {'amount': '0.00', 'amount_currency': 'EUR'}
        ]

    def test_zero_and_nonzero_values(self):
        t = Total(100, 'USD', 0, 'EUR')
        assert TotalSerializer(t).data == [
            {'amount': '100.00', 'amount_currency': 'USD'}
        ]
        assert TotalIncludingZeroSerializer(t).data == [
            {'amount': '100.00', 'amount_currency': 'USD'},
            {'amount': '0.00', 'amount_currency': 'EUR'}
        ]
