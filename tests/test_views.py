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

        with self.assertNumQueries(9):  # XXX: this is a lot
            response = client.get(reverse('billing_account'))
        assert response.status_code == HTTP_200_OK
        assert response.json() == {
            "id": "016e8ed0-8786-4ffc-b5e0-bf2b919c8d2b",
            "balance": [
                {
                    "amount_currency": "USD",
                    "amount": "-15.00"
                }
            ],
            "credit_cards": [
                {
                    "id": "f4eda79e-ba6b-45d5-b0c4-7cd039229bae",
                    "created": "2017-10-21T06:35:49.581000-05:00",
                    "type": "VIS",
                    "number": "1111",
                    "expiry_month": 1,
                    "expiry_year": 18
                }
            ],
            "charges": [
                {
                    "id": "4b312d25-3567-42d2-acce-e77b3d422479",
                    "created": "2017-10-21T03:49:27.746000-05:00",
                    "amount_currency": "USD",
                    "amount": "15.00",
                    "description": "",
                    "invoice": 1
                }
            ],
            "invoices": [
                {
                    "id": 1,
                    "total": [
                        {
                            "amount_currency": "USD",
                            "amount": "15.00"
                        }
                    ],
                    "created": "2017-10-21T03:49:41.728000-05:00",
                    "status": "PAST_DUE"
                },
                {
                    "id": 2,
                    "total": [

                    ],
                    "created": "2017-10-21T04:47:14.554000-05:00",
                    "status": "PENDING"
                }
            ],
            "transactions": [

            ],
            "created": "2017-10-21T03:49:07.090000-05:00",
            "currency": "USD",
            "status": "OPEN"
        }
