from contextlib import contextmanager
from unittest import mock

from django.db.models import Model


@contextmanager
def catch_signal(signal):
    """
    Catch django signal and return the mocked call.
    From https://medium.freecodecamp.org/how-to-testing-django-signals-like-a-pro-c7ed74279311
    """
    handler = mock.Mock()
    signal.connect(handler)
    yield handler
    signal.disconnect(handler)


@contextmanager
def silence_signal(signal):
    receivers = signal.receivers
    signal.receivers = []
    yield
    signal.receivers = receivers


def assert_attrs(entity, expected_attrs):
    """
    Assert that an entity has the given attributes.
    Follows relationships as needed.
    """
    for k, expected in expected_attrs.items():
        attr = getattr(entity, k)
        if callable(getattr(attr, 'all', None)):
            # It's a to-many relation we can folow
            related_entities = list(attr.all())
            assert len(expected) == len(related_entities), \
                '{} has {} elements, expected {}.'.format(k, len(related_entities), len(expected))
            for i, related_expected_attrs in enumerate(expected):
                assert_attrs(related_entities[i], related_expected_attrs)
        elif isinstance(attr, Model):
            assert_attrs(attr, expected)
        else:
            assert attr == expected, '{} was {}, expected {}'.format(k, attr, expected)
