from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from django.db import connection
from django.db.models import Q
from django.contrib.auth.models import update_last_login
from django.core.validators import validate_email
from django_tenants.utils import get_public_schema_name
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.settings import api_settings
from .models import User


def is_valid_phone_number(value):
    import re

    # Accept common local or international digit-only phone formats.
    return bool(re.match(r'^\+?\d{8,15}$', value or ''))


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True, required=False)
    full_name = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'phone', 'password', 'confirm_password', 'full_name', 'role']

    def validate_email(self, value):
        if value:
            try:
                validate_email(value)
            except DjangoValidationError:
                raise serializers.ValidationError("Please enter a valid email address.")

            # Check if email already exists
            if User.objects.filter(email__iexact=value).exists():
                raise serializers.ValidationError("This email is already registered.")

        return value

    def validate_phone(self, value):
        if value:
            if not is_valid_phone_number(value):
                raise serializers.ValidationError("Please enter a valid phone number.")

            # Check if phone already exists
            if User.objects.filter(phone=value).exists():
                raise serializers.ValidationError("This phone number is already registered.")

        return value

    def validate_password(self, value):
        if not value:
            raise serializers.ValidationError("Password is required.")

        # Password strength validation
        if len(value) < 8:
            raise serializers.ValidationError("Password must be at least 8 characters long.")

        import re
        if not re.search(r'[a-z]', value):
            raise serializers.ValidationError("Password must contain at least one lowercase letter.")

        if not re.search(r'[A-Z]', value):
            raise serializers.ValidationError("Password must contain at least one uppercase letter.")

        if not re.search(r'\d', value):
            raise serializers.ValidationError("Password must contain at least one number.")

        if not re.search(r'[@$!%*?&]', value):
            raise serializers.ValidationError("Password must contain at least one special character (@$!%*?&).")

        return value

    def validate(self, attrs):
        email = attrs.get("email")
        phone = attrs.get("phone")
        password = attrs.get("password")
        confirm_password = attrs.get("confirm_password")
        full_name = attrs.get("full_name")

        # Check that at least email or phone is provided
        if not email and not phone:
            raise serializers.ValidationError(
                "Either email or phone must be provided."
            )

        # Validate full name if provided
        if full_name and len(full_name.strip()) < 2:
            raise serializers.ValidationError("Full name must be at least 2 characters long.")

        # Validate password confirmation
        if confirm_password and password != confirm_password:
            raise serializers.ValidationError("Passwords do not match.")

        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password')
        validated_data.pop('confirm_password', None)  # Remove confirm_password if present
        full_name = validated_data.pop('full_name', None)

        tenant = getattr(connection, 'tenant', None)
        if tenant is not None and connection.schema_name != get_public_schema_name():
            validated_data.setdefault('tenant', tenant)

        user = User.objects.create_user(
            password=password,
            **validated_data
        )

        # Set full_name if provided
        if full_name:
            user.full_name = full_name

        user.save()

        return user


class UserSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'name']

    def get_name(self, obj):
        # Return email if exists, otherwise phone
        return obj.email if obj.email else obj.phone


class CurrentUserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    tenant_id = serializers.IntegerField(read_only=True)
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'email',
            'phone',
            'role',
            'full_name',
            'tenant_id',
            'is_staff',
            'is_superuser',
            'email_verified',
            'password_set_at',
            'permissions',
        ]

    def get_full_name(self, obj):
        # Use the user's own full_name field; trainer-specific data lives in TrainerProfile
        if obj.full_name:
            return obj.full_name
        if obj.role in ['admin', 'staff', 'superuser']:
            return obj.email or obj.phone
        return obj.full_name or obj.email or obj.phone

    def get_permissions(self, obj):
        return []


class CurrentUserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['email', 'phone']
        extra_kwargs = {
            'email': {'required': False, 'allow_null': True, 'allow_blank': True},
            'phone': {'required': False, 'allow_null': True, 'allow_blank': True},
        }

    def validate_email(self, value):
        if not value:
            return value

        try:
            validate_email(value)
        except DjangoValidationError:
            raise serializers.ValidationError('Please enter a valid email address.')

        user_qs = User.objects.filter(email__iexact=value)
        if self.instance is not None:
            user_qs = user_qs.exclude(pk=self.instance.pk)

        if user_qs.exists():
            raise serializers.ValidationError('This email is already registered.')

        return value

    def validate_phone(self, value):
        if not value:
            return value

        if not is_valid_phone_number(value):
            raise serializers.ValidationError('Please enter a valid phone number.')

        user_qs = User.objects.filter(phone=value)
        if self.instance is not None:
            user_qs = user_qs.exclude(pk=self.instance.pk)

        if user_qs.exists():
            raise serializers.ValidationError('This phone number is already registered.')

        return value

    def validate(self, attrs):
        next_email = attrs.get('email', self.instance.email if self.instance else None)
        next_phone = attrs.get('phone', self.instance.phone if self.instance else None)

        if not next_email and not next_phone:
            raise serializers.ValidationError('Either email or phone must be provided.')

        return attrs


class EmailOrPhoneTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Accept email/phone/identifier with password and issue JWT tokens.
    Keeps backward compatibility with current frontend payload that uses `email`.

    The issued JWT contains two extra claims so the frontend can identify
    the tenant context:
      - tenant_schema: the PostgreSQL schema name of the active tenant
      - tenant_name:   the human-readable name of the active tenant
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Embed tenant context so the frontend can read it from the JWT
        # without an extra API call.
        token['tenant_schema'] = connection.schema_name
        tenant = getattr(connection, 'tenant', None)
        token['tenant_name'] = tenant.name if tenant is not None else None
        from utils.jwt_sessions import embed_token_version

        embed_token_version(token, user)
        return token

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # SimpleJWT marks USERNAME_FIELD as required by default.
        # Make it optional so phone/identifier payloads are accepted too.
        self.fields[self.username_field].required = False
        self.fields[self.username_field].allow_blank = True
        self.fields["phone"] = serializers.CharField(required=False, allow_blank=True, write_only=True)
        self.fields["identifier"] = serializers.CharField(required=False, allow_blank=True, write_only=True)

    def _resolve_identifier(self):
        data = self.initial_data
        identifier = data.get("email") or data.get("phone") or data.get("identifier")
        return identifier.strip() if isinstance(identifier, str) else identifier

    def _get_user_from_identifier(self, identifier):
        return User.objects.filter(
            Q(email__iexact=identifier) | Q(phone=identifier)
        ).first()

    def validate(self, attrs):
        identifier = self._resolve_identifier()
        password = self.initial_data.get("password")
        tenant = getattr(connection, 'tenant', None)

        # Validate identifier (email/phone)
        if not identifier:
            raise AuthenticationFailed("Email or phone number is required.")

        # Validate identifier format
        import re
        if '@' in identifier:
            # Email format validation
            try:
                validate_email(identifier)
            except DjangoValidationError:
                raise AuthenticationFailed("Please enter a valid email address.")
        else:
            if not is_valid_phone_number(identifier):
                raise AuthenticationFailed("Please enter a valid phone number.")

        # Validate password
        if not password:
            raise AuthenticationFailed("Password is required.")

        # Basic password validation (same as registration)
        if len(password) < 8:
            raise AuthenticationFailed("Password must be at least 8 characters long.")

        user = self._get_user_from_identifier(identifier)

        if not user or not user.check_password(password):
            raise AuthenticationFailed("No active account found with the given credentials")

        if not user.is_active:
            raise AuthenticationFailed("User account is disabled.")

        if tenant is not None and not tenant.allows_user_entry():
            raise AuthenticationFailed("Tenant workspace is suspended.")

        if tenant is not None and connection.schema_name != get_public_schema_name() and user.tenant_id is None:
            user.tenant = tenant
            user.save(update_fields=['tenant'])

        refresh = self.get_token(user)
        data = {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }

        if api_settings.UPDATE_LAST_LOGIN:
            update_last_login(None, user)

        return data
