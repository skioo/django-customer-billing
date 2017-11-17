from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from rest_framework.status import HTTP_200_OK
from rest_framework.test import APIClient


class AccountViewTest(TestCase):
    fixtures = ['tests/sample-data']

    def test_it_should_retrieve_user111s_account(self):
        user111 = User.objects.get(id=111)
        client = APIClient()
        client.force_authenticate(user111)

        with self.assertNumQueries(9):
            response = client.get(reverse('billing_account'))
        assert response.status_code == HTTP_200_OK
        assert response.json() == {
            'id': '016e8ed0-8786-4ffc-b5e0-bf2b919c8d2b',
            'created': '2017-10-21T03:49:07.090000-05:00',
            'modified': '2017-10-22T17:22:22.090000-05:00',
            'currency': 'USD',
            'credit_cards': [
                {'id': 'f4eda79e-ba6b-45d5-b0c4-7cd039229bae',
                 'created': '2017-10-21T06:35:49.581000-05:00',
                 'modified': '2017-10-22T17:22:22.090000-05:00',
                 'expiry_year': 18,
                 'expiry_month': 1,
                 'number': '1111',
                 'type': 'VIS'
                 }
            ], 'transactions': [
            ], 'charges': [
                {
                    'id': '4b312d25-3567-42d2-acce-e77b3d422479',
                    'created': '2017-10-21T03:49:27.746000-05:00',
                    'modified': '2017-10-22T17:22:22.090000-05:00',
                    'invoice': 1,
                    'description': '',
                    'amount': '15.00',
                    'amount_currency': 'USD'}
            ],
            'status': 'OPEN',
            'balance': [
                {'amount': '-15.00', 'amount_currency': 'USD'}
            ],
            'invoices': [
                {
                    'id': 1,
                    'created': '2017-10-21T03:49:41.728000-05:00',
                    'modified': '2017-10-22T17:22:22.090000-05:00',
                    'status': 'PAST_DUE',
                    'total': [{'amount': '15.00', 'amount_currency': 'USD'}]
                },
                {
                    'id': 2,
                    'status': 'PENDING',
                    'created': '2017-10-21T04:47:14.554000-05:00',
                    'modified': '2017-10-22T17:22:22.090000-05:00',
                    'total': []
                }
            ]
        }
