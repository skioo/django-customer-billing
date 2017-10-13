from ..models import Account


def close(account: Account) -> None:
    account.close()
    account.save()


def reopen(account: Account) -> None:
    account.reopen()
    account.save()
