from moneyed import Money
from typing import Tuple

from billing.psp import PSP


class MyPSP(PSP):
    def admin_url(self, object_psp_path: str) -> str:
        return 'this-doesnt-make-much-sense-for-the-test-psp'

    def charge_credit_card(self, credit_card_psp_path: str, amount: Money, client_ref: str) -> Tuple[bool, str]:
        return True, 'payment/1234'

    def refund_payment(self, payment_psp_path: str, amount: Money, client_ref: str) -> Tuple[bool, str]:
        return True, 'refund/2345'
