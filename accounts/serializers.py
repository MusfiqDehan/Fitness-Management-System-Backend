from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from django.db.models import Q
from django.contrib.auth.models import update_last_login
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.settings import api_settings
from .models import User, StudentProfile, InstructorProfile


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'phone', 'password', 'role']

    def validate(self, attrs):
        email = attrs.get("email")
        phone = attrs.get("phone")

        if not email and not phone:
            raise serializers.ValidationError(
                "Either email or phone must be provided."
            )

        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password')

        user = User.objects.create_user(
            **validated_data
        )
        user.set_password(password)
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

        if not identifier or not password:
            raise AuthenticationFailed("Must include login identifier and password.")

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