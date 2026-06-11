import json

from rest_framework import serializers

from apps.identity.models import User
from .models import Branch, BranchShiftRequest, Facility


class FacilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Facility
        fields = ["id", "name"]


class BranchSerializer(serializers.ModelSerializer):
    facilities = FacilitySerializer(many=True, required=False)
    manager = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False, allow_null=True
    )
    manager_name = serializers.SerializerMethodField(read_only=True)
    members_count = serializers.SerializerMethodField(read_only=True)
    trainers_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Branch
        fields = [
            "id",
            "name",
            "code",
            "city",
            "location",
            "address",
            "description",
            "manager",
            "manager_name",
            "phone_number",
            "email",
            "operating_hours",
            "opening_time",
            "closing_time",
            "weekdays_hours",
            "weekend_hours",
            "opening_date",
            "status",
            "capacity",
            "staff_count",
            "classes_per_week",
            "monthly_revenue",
            "revenue_trend",
            "rating",
            "facilities",
            "image",
            "homepage_image",
            "website",
            "show_on_homepage",
            "is_flagship",
            "display_order",
            "is_active",
            "members_count",
            "trainers_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_manager_name(self, obj):
        if obj.manager_id:
            return getattr(obj.manager, "full_name", None) or obj.manager.email
        return None

    def get_members_count(self, obj):
        if hasattr(obj, "members_count"):
            return obj.members_count
        return obj.members.count() if hasattr(obj, "members") else 0

    def get_trainers_count(self, obj):
        if hasattr(obj, "trainers_count"):
            return obj.trainers_count
        return obj.trainers.count() if hasattr(obj, "trainers") else 0

    # ── Facility JSON normalisation (supports multipart string payloads) ──
    def _normalize_facilities(self, facilities):
        if facilities is None:
            return None

        if isinstance(facilities, str):
            try:
                facilities = json.loads(facilities)
            except json.JSONDecodeError as exc:
                raise serializers.ValidationError(
                    {"facilities": "Provide a valid JSON array of facility objects."}
                ) from exc

        if not isinstance(facilities, list):
            raise serializers.ValidationError(
                {"facilities": "Expected a list of facility objects."}
            )

        normalized = []
        for index, facility in enumerate(facilities):
            if isinstance(facility, str):
                name = facility
            elif isinstance(facility, dict):
                name = facility.get("name")
            else:
                raise serializers.ValidationError(
                    {"facilities": f"Facility at index {index} must be an object or string."}
                )
            if not isinstance(name, str) or not name.strip():
                raise serializers.ValidationError(
                    {"facilities": f"Facility at index {index} must include a non-empty name."}
                )
            normalized.append({"name": name.strip()})
        return normalized

    def _set_facilities(self, branch, facilities_data):
        for facility in facilities_data:
            obj, _ = Facility.objects.get_or_create(name=facility["name"])
            branch.facilities.add(obj)

    def to_internal_value(self, data):
        normalized_data = {}
        if hasattr(data, "lists"):
            for key, values in data.lists():
                normalized_data[key] = values if len(values) > 1 else values[0]
        elif hasattr(data, "copy"):
            normalized_data = data.copy()
        else:
            normalized_data = dict(data)

        facilities = self._normalize_facilities(normalized_data.get("facilities"))
        if facilities is not None:
            normalized_data["facilities"] = facilities

        return super().to_internal_value(normalized_data)

    def create(self, validated_data):
        facilities_data = validated_data.pop("facilities", [])
        branch = Branch.objects.create(**validated_data)
        self._set_facilities(branch, facilities_data)
        return branch

    def update(self, instance, validated_data):
        facilities_data = validated_data.pop("facilities", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if facilities_data is not None:
            instance.facilities.clear()
            self._set_facilities(instance, facilities_data)
        return instance


class BranchMinimalSerializer(serializers.ModelSerializer):
    """Lightweight branch representation for public dropdowns/listings."""

    class Meta:
        model = Branch
        fields = ["id", "name", "city", "address"]


class BranchShiftRequestSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source="member.full_name", read_only=True)
    trainer_name = serializers.CharField(
        source="trainer.user.full_name", read_only=True
    )
    from_branch_name = serializers.CharField(source="from_branch.name", read_only=True)
    to_branch_name = serializers.CharField(source="to_branch.name", read_only=True)

    class Meta:
        model = BranchShiftRequest
        fields = [
            "id",
            "member",
            "member_name",
            "trainer",
            "trainer_name",
            "from_branch",
            "from_branch_name",
            "to_branch",
            "to_branch_name",
            "status",
            "reason",
            "decision_note",
            "reviewed_by",
            "reviewed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "status",
            "from_branch",
            "decision_note",
            "reviewed_by",
            "reviewed_at",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        member = attrs.get("member")
        trainer = attrs.get("trainer")
        if not member and not trainer:
            raise serializers.ValidationError(
                "A shift request must reference either a member or a trainer."
            )
        if member and trainer:
            raise serializers.ValidationError(
                "A shift request cannot reference both a member and a trainer."
            )
        return attrs
