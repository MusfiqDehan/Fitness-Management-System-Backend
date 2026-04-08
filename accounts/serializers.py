from rest_framework import serializers
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