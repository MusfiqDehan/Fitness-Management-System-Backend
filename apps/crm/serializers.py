from rest_framework import serializers

from .models import ContactQuery, EmailConfig


class ContactQuerySerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactQuery
        fields = [
            "id",
            "full_name",
            "phone_number",
            "email",
            "package_name",
            "message",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class EmailConfigSerializer(serializers.ModelSerializer):
    """Serializer for EmailConfig.  host_password is write-only."""

    host_password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        style={"input_type": "password"},
    )

    class Meta:
        model = EmailConfig
        fields = [
            "id",
            "name",
            "email_backend",
            "host",
            "port",
            "use_tls",
            "use_ssl",
            "host_user",
            "host_password",
            "default_from_email",
            "contact_email",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_active", "created_at", "updated_at"]

    def update(self, instance, validated_data):
        # Never wipe the stored password when it is omitted from a PATCH/PUT
        if "host_password" in validated_data and not validated_data["host_password"]:
            validated_data.pop("host_password")
        return super().update(instance, validated_data)
