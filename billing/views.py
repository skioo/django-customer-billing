from django.http import Http404
from rest_framework import permissions, serializers
from rest_framework.decorators import permission_classes
from rest_framework.generics import RetrieveAPIView
from rest_framework.mixins import UpdateModelMixin, RetrieveModelMixin, ListModelMixin
from rest_framework.viewsets import GenericViewSet

from .models import Account, Charge, CreditCard, Invoice, Transaction, ProductProperty
from .total import TotalSerializer, TotalIncludingZeroSerializer


class CreditCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditCard
        exclude = ['account', 'expiry_date', 'psp_content_type', 'psp_object_id']


class CreditCardUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditCard
        fields = ['status']

    def update(self, instance, validated_data):
        new_status = validated_data['status']
        if new_status == CreditCard.INACTIVE:
            instance.deactivate()
        elif new_status == CreditCard.ACTIVE:
            instance.reactivate()
        else:
            raise Exception('Unknown status')
        instance.save()
        return instance


@permission_classes([permissions.IsAuthenticated])
class CreditCardViewSet(ListModelMixin, RetrieveModelMixin, UpdateModelMixin, GenericViewSet):
    """
    list: Return the list of credit cards registered on the account.
    retrieve: Return the credit card information
    partial_update: Change the status of the creditcard.
    """
    http_method_names = ['get', 'patch']  # We don't want put (inherited from UpdateModelMixin)

    def get_queryset(self):
        return CreditCard.objects.filter(account__owner=self.request.user)

    def get_serializer_class(self):
        method = self.request.method
        if method == 'GET':
            return CreditCardSerializer
        elif method == 'PATCH':
            return CreditCardUpdateSerializer
        else:
            raise Exception('Unknown method')


########################################################################################################

class ProductPropertyListSerializer(serializers.ListSerializer):
    # From: https://stackoverflow.com/questions/31583445
    def to_representation(self, data):
        r = super().to_representation(data)
        return {item['name']: item['value'] for item in r}


class ProductPropertySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductProperty
        fields = ['name', 'value']
        list_serializer_class = ProductPropertyListSerializer


class ChargeSerializer(serializers.ModelSerializer):
    product_properties = ProductPropertySerializer(read_only=True, many=True)

    class Meta:
        model = Charge
        exclude = ['account', 'deleted', 'reverses']


########################################################################################################

class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        exclude = ['account', 'psp_content_type', 'psp_object_id']


########################################################################################################

class InvoiceSerializer(serializers.ModelSerializer):
    due = TotalIncludingZeroSerializer(read_only=True)
    # We keep the old 'total' field name for API compatiblity.
    total = TotalSerializer(source='total_charges', read_only=True)

    class Meta:
        model = Invoice
        exclude = ['account']


########################################################################################################

class AccountSerializer(serializers.ModelSerializer):
    balance = TotalSerializer(read_only=True)
    credit_cards = CreditCardSerializer(read_only=True, many=True)
    charges = ChargeSerializer(read_only=True, many=True)
    invoices = InvoiceSerializer(read_only=True, many=True)
    transactions = TransactionSerializer(read_only=True, many=True)

    class Meta:
        model = Account
        exclude = ['owner']


@permission_classes([permissions.IsAuthenticated])
class AccountView(RetrieveAPIView):
    """
    get: Retrieve the full billing account information.
    """
    serializer_class = AccountSerializer
    pagination_class = None

    def get_object(self):
        try:
            return Account.objects.open() \
                .prefetch_related('invoices') \
                .prefetch_related('credit_cards') \
                .prefetch_related('transactions') \
                .prefetch_related('charges__product_properties') \
                .get(owner=self.request.user)
        except Account.DoesNotExist:
            raise Http404('No Account matches the given query.')
