from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from django.db.models import Q
from django.contrib.auth.models import update_last_login
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.settings import api_settings
from .models import User, StudentProfile, InstructorProfile


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True, required=False)
    full_name = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'phone', 'password', 'confirm_password', 'full_name', 'role']

    def validate_email(self, value):
        if value:
            # Email format validation
            from django.core.validators import validate_email
            from django.core.exceptions import ValidationError as DjangoValidationError
            
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
            # Phone number validation (basic format check)
            import re
            if not re.match(r'^\+?[1-9]\d{1,14}$', value):
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

        user = User.objects.create_user(
            **validated_data
        )
        user.set_password(password)
        
        # Set full_name if provided
        if full_name:
            user.full_name = full_name
        
        user.save()

        return user

class StudentProfileSerializer(serializers.ModelSerializer):

    class Meta:
        model = StudentProfile
        exclude = ['user']


class InstructorProfileSerializer(serializers.ModelSerializer):

    class Meta:
        model = InstructorProfile
        exclude = ['user']

class UserSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'name']

    def get_name(self, obj):
        # Return email if exists, otherwise phone
        return obj.email if obj.email else obj.phone


class EmailOrPhoneTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Accept email/phone/identifier with password and issue JWT tokens.
    Keeps backward compatibility with current frontend payload that uses `email`.
    """

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

        # Validate identifier (email/phone)
        if not identifier:
            raise AuthenticationFailed("Email or phone number is required.")
        
        # Validate identifier format
        import re
        if '@' in identifier:
            # Email format validation
            from django.core.validators import validate_email
            from django.core.exceptions import ValidationError as DjangoValidationError
            
            try:
                validate_email(identifier)
            except DjangoValidationError:
                raise AuthenticationFailed("Please enter a valid email address.")
        else:
            # Phone format validation
            if not re.match(r'^\+?[1-9]\d{1,14}$', identifier):
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

        refresh = self.get_token(user)
        data = {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }

        if api_settings.UPDATE_LAST_LOGIN:
            update_last_login(None, user)

        return data