from rest_framework import serializers
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            'id', 'notification_type', 'title', 'message',
            'actor_name', 'actor_email', 'target_type', 'target_id',
            'metadata', 'is_active', 'created_at', 'updated_at', 'is_read',
        ]
        read_only_fields = fields

    def get_is_read(self, obj):
        read_ids = self.context.get('read_ids', set())
        return obj.id in read_ids
