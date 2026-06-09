from rest_framework import serializers
import json
from .models import (
    GymClass,
    Category,
    ClassSchedule,
    Blog,
    BlogCategory,
    Contact,
    FitHiveSupport,
    ClassBooking,
    Package,
    PackageFeature,
    PackageAddOn,
    GymSchedule,
)
from django.utils import timezone
from apps.identity.models import InstructorProfile


# class
class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name"]


class ClassScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClassSchedule
        fields = ["id", "day", "time"]


class GymScheduleSerializer(serializers.ModelSerializer):
    time = serializers.TimeField(format='%H:%M', input_formats=['%H:%M', '%H:%M:%S'])

    class Meta:
        model = GymSchedule
        fields = [
            'id', 'class_name', 'instructor', 'day', 'time',
            'duration_minutes', 'location', 'capacity',
            'difficulty_level', 'category', 'description',
            'is_active', 'display_order', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class GymClassSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(),
        source="category",
        write_only=True
    )

    class_schedule = ClassScheduleSerializer(read_only=True, many=True)
    class_schedule_ids = serializers.PrimaryKeyRelatedField(
        queryset=ClassSchedule.objects.all(),
        source="class_schedule",
        write_only=True,
        many=True
    )
    instructor_name = serializers.SerializerMethodField()

    class Meta:
        model = GymClass
        fields = [
            "id",
            "title",
            "image",
            "description",
            "category",
            "category_id",
            "class_duration",
            "people",
            "level",
            "class_schedule",
            "class_schedule_ids",
            "created_at",
            'is_show_on_home_page',
            'is_active',
            'instructor',
            'instructor_name'
        ]

    def get_instructor_name(self, obj):
        if obj.instructor:
            # Try to get the related InstructorProfile
            profile = getattr(obj.instructor, 'instructor_profile', None)
            if profile:
                return profile.full_name
            # Fallback to email if profile missing
            return obj.instructor.email
        return None


class ClassBookingSerializer(serializers.ModelSerializer):
    class_name = serializers.CharField(source="gym_class.title", read_only=True)
    instructor = serializers.SerializerMethodField()
    class_duration = serializers.CharField(source="gym_class.class_duration", read_only=True)
    user_name = serializers.SerializerMethodField()
    user_email = serializers.CharField(source="user.email", read_only=True)

    selected_schedule = ClassScheduleSerializer(read_only=True)
    selected_schedule_id = serializers.PrimaryKeyRelatedField(
        queryset=ClassSchedule.objects.all(),
        source="selected_schedule",
        write_only=True,
        required=False,
        allow_null=True,
    )

    schedules = serializers.SerializerMethodField()

    class Meta:
        model = ClassBooking
        fields = "__all__"
        read_only_fields = ("user", "created_at")

    def get_instructor(self, obj):
        instructor = getattr(obj.gym_class, 'instructor', None)
        if instructor is None:
            return None
        profile = getattr(instructor, 'instructor_profile', None)
        if profile:
            return profile.full_name
        return instructor.email

    def get_user_name(self, obj):
        profile = getattr(obj.user, 'student_profile', None)
        if profile:
            return profile.full_name
        return obj.user.email

    def get_schedules(self, obj):
        return [
            {
                "id": schedule.id,
                "day": schedule.day,
                "time": schedule.time
            }
            for schedule in obj.gym_class.class_schedule.all()
        ]


# --- Blog Serializers ---

class BlogCategorySerializer(serializers.ModelSerializer):
    def validate_name(self, value):
        normalized_value = value.strip()
        if not normalized_value:
            raise serializers.ValidationError('This field may not be blank.')

        existing_categories = BlogCategory.objects.filter(name__iexact=normalized_value)
        if self.instance is not None:
            existing_categories = existing_categories.exclude(pk=self.instance.pk)

        if existing_categories.exists():
            raise serializers.ValidationError('A blog category with this name already exists.')

        return normalized_value

    class Meta:
        model = BlogCategory
        fields = ['id', 'name', 'slug']


class DashboardBlogSerializer(serializers.ModelSerializer):
    # Read category as nested for GET, write as PK for POST/PUT
    category = BlogCategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=BlogCategory.objects.all(),
        source='category',
        write_only=True
    )
    image = serializers.ImageField(required=False)

    class Meta:
        model = Blog
        fields = [
            'id',
            'title',
            'slug',
            'excerpt',
            'description',
            'image',
            'category',
            'category_id',   # this is required for create/update
            'status',
            'is_show_on_home_page',
            'author',
            'published_date',
            'created_at',
        ]
        read_only_fields = ['author', 'published_date', 'created_at']

    def create(self, validated_data):
        # Assign author automatically
        validated_data['author'] = self.context['request'].user

        # Set published_date if status is published
        if validated_data.get('status') == 'published':
            validated_data['published_date'] = timezone.now()

        return super().create(validated_data)

    def update(self, instance, validated_data):
        if validated_data.get('status') == 'published' and not instance.published_date:
            validated_data['published_date'] = timezone.now()
        return super().update(instance, validated_data)


class BlogListSerializer(serializers.ModelSerializer):
    category = BlogCategorySerializer()

    class Meta:
        model = Blog
        fields = [
            'id',
            'title',
            'slug',
            'image',
            'category',
            'status',
            'published_date',
            'created_at',
            'excerpt',
        ]


class BlogDetailSerializer(serializers.ModelSerializer):
    category = BlogCategorySerializer()

    class Meta:
        model = Blog
        fields = '__all__'


# --- Contact Serializer ---

class ContactCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = [
            "id",
            "name",
            "email",
            "phone",
            "preferred_branch",
            "subject",
            "message",
        ]


class ContactDashboardSerializer(serializers.ModelSerializer):
    preferred_branch_name = serializers.CharField(
        source="preferred_branch.name",
        read_only=True
    )

    class Meta:
        model = Contact
        fields = "__all__"


# --- FitHive Support Serializer ---
class FitHiveSupportCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = FitHiveSupport
        fields = [
            "id",
            "name",
            "email",
            "phone",
            "interested_in",
        ]


class FitHiveSupportDashboardSerializer(serializers.ModelSerializer):
    class Meta:
        model = FitHiveSupport
        fields = "__all__"


# -- package manager --
class PackageFeatureSerializer(serializers.ModelSerializer):
    def validate_feature(self, value):
        normalized_value = value.strip()
        if not normalized_value:
            raise serializers.ValidationError('This field may not be blank.')
        return normalized_value

    class Meta:
        model = PackageFeature
        fields = ['id', 'feature']


class PackageAddOnSerializer(serializers.ModelSerializer):
    def validate_name(self, value):
        normalized_value = value.strip()
        if not normalized_value:
            raise serializers.ValidationError('This field may not be blank.')
        return normalized_value

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError('Price must be zero or greater.')
        return value

    class Meta:
        model = PackageAddOn
        fields = ['id', 'name', 'price', 'description', 'is_active']


class PackageSerializer(serializers.ModelSerializer):
    features = PackageFeatureSerializer(many=True)
    addons = PackageAddOnSerializer(many=True)

    class Meta:
        model = Package
        fields = [
            'id',
            'name',
            'duration',
            'price',
            'display_order',
            'description',
            'is_popular',
            'is_active',
            'features',
            'addons',
        ]

    def validate_name(self, value):
        normalized_value = value.strip()
        if not normalized_value:
            raise serializers.ValidationError('This field may not be blank.')
        return normalized_value

    def create(self, validated_data):
        features_data = validated_data.pop('features', [])
        addons_data = validated_data.pop('addons', [])

        package = Package.objects.create(**validated_data)

        # Create features
        for feature in features_data:
            PackageFeature.objects.create(
                package=package,
                feature=feature['feature']
            )

        # Create addons
        for addon in addons_data:
            PackageAddOn.objects.create(
                package=package,
                name=addon['name'],
                price=addon['price'],
                description=addon.get('description', ''),
                is_active=addon.get('is_active', True)
            )

        return package

    def update(self, instance, validated_data):
        features_data = validated_data.pop('features', None)
        addons_data = validated_data.pop('addons', None)

        # Update main package fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if features_data is not None:
            #  Replace features
            instance.features.all().delete()
            for feature in features_data:
                PackageFeature.objects.create(
                    package=instance,
                    feature=feature['feature']
                )

        if addons_data is not None:
            #  Replace addons
            instance.addons.all().delete()
            for addon in addons_data:
                PackageAddOn.objects.create(
                    package=instance,
                    name=addon['name'],
                    price=addon['price'],
                    description=addon.get('description', ''),
                    is_active=addon.get('is_active', True)
                )

        return instance